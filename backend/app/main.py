import asyncio
import hashlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from sqlalchemy import select, text
from .config import settings
from .db import engine, get_db, Session
from .errors import AppError
from .keitaro import tracker, seed_demo
from .models import Campaign, Operation, LoginSession
from . import schemas as schema, services as svc

# One application worker is intentional: serializes mutations across the local and external stores.
# Reads remain concurrent. Database constraints still enforce identifier uniqueness.
mutation_lock = asyncio.Lock()
login_attempts: dict[str, list[float]] = {}


@asynccontextmanager
async def lifespan(app):
    cfg = settings()
    if cfg.keitaro_mode not in ("demo", "live"):
        raise RuntimeError("KEITARO_MODE must be demo or live")
    if cfg.keitaro_mode == "live" and (not cfg.keitaro_url.startswith("https://") or not cfg.keitaro_api_key or len(cfg.operator_password) < 12):
        raise RuntimeError("Live mode requires HTTPS KEITARO_URL, KEITARO_API_KEY and OPERATOR_PASSWORD (12+ characters).")
    # Schema is managed by `alembic upgrade head`, not by implicit create_all.
    async with Session() as db:
        pending = (await db.scalars(select(Operation).where(Operation.status == "running"))).all()
        for op in pending:
            op.status, op.error = "unknown", "Приложение перезапущено во время операции. Выполните сверку."
        await db.commit()
    if cfg.keitaro_mode == "demo":
        await seed_demo()
        async with Session() as db:
            if not await db.scalar(select(Campaign.id).limit(1)):
                await svc.import_campaign(db, tracker(), 93212)
    yield
    await engine.dispose()


app = FastAPI(title="Adrobot API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings().frontend_origin], allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "X-Requested-With", "Idempotency-Key"])


def openapi_schema():
    if app.openapi_schema:
        return app.openapi_schema
    document = get_openapi(title=app.title, version=app.version, routes=app.routes)
    document.setdefault("components", {}).setdefault("securitySchemes", {})["AdrobotHeader"] = {
        "type": "apiKey", "in": "header", "name": "X-Requested-With",
        "description": "Введите Adrobot. Для рабочего режима также войдите через auth/login (cookie-сессия).",
    }
    document["security"] = [{"AdrobotHeader": []}]
    app.openapi_schema = document
    return document


app.openapi = openapi_schema


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    if request.method in ("POST", "PATCH", "DELETE", "PUT"):
        origin = request.headers.get("origin")
        allowed = {settings().frontend_origin, str(request.base_url).rstrip("/")}
        if settings().keitaro_mode == "demo":
            allowed.update({"http://localhost:5173", "http://127.0.0.1:5173"})
        if request.headers.get("x-requested-with") != "Adrobot" or (origin and origin not in allowed):
            return JSONResponse({"error": {"code": "CSRF", "message": "Недопустимый источник запроса.", "request_id": request.state.request_id}}, status_code=403)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AppError)
async def app_error(request, exc):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message, "details": exc.details,
                                   "request_id": request.state.request_id}}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({"error": {"code": "VALIDATION", "message": "Проверьте заполнение полей.",
                                   "details": [{"field": ".".join(map(str, x["loc"])), "message": x["msg"]} for x in exc.errors()],
                                   "request_id": request.state.request_id}}, status_code=422)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    import logging
    logging.getLogger("adrobot").exception("Request %s failed", request.state.request_id)
    return JSONResponse({"error": {"code": "INTERNAL", "message": "Внутренняя ошибка. Данные черновика сохранены; обновите страницу.",
                                   "request_id": request.state.request_id}}, status_code=500)


async def authenticated(request: Request, db=Depends(get_db)):
    if not settings().operator_password and settings().keitaro_mode == "demo":
        return
    token = request.cookies.get("adrobot_session", "")
    row = await db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest())
    if not row or row.expires < int(time.time()):
        raise AppError("AUTH_REQUIRED", "Войдите в приложение.", 401)


auth = [Depends(authenticated)]


@app.get("/api/v1/auth/me")
async def me(request: Request, db=Depends(get_db)):
    try:
        await authenticated(request, db)
        logged_in = True
    except AppError:
        logged_in = False
    return {"authenticated": logged_in, "requires_login": bool(settings().operator_password), "mode": settings().keitaro_mode}


@app.post("/api/v1/auth/login")
async def login(body: schema.Login, request: Request, response: Response, db=Depends(get_db)):
    host = request.client.host if request.client else "unknown"
    recent = [t for t in login_attempts.get(host, []) if time.time() - t < 300]
    login_attempts[host] = recent
    if len(recent) >= 10:
        raise AppError("RATE_LIMIT", "Слишком много попыток. Повторите через 5 минут.", 429)
    if not settings().operator_password or not hmac.compare_digest(body.password.encode(), settings().operator_password.encode()):
        recent.append(time.time())
        raise AppError("LOGIN_FAILED", "Неверный пароль.", 401)
    login_attempts.pop(host, None)
    token = secrets.token_urlsafe(40)
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), expires=int(time.time()) + 43200))
    await db.commit()
    response.set_cookie("adrobot_session", token, httponly=True, secure=settings().cookie_secure, samesite="strict", max_age=43200)
    return {"authenticated": True}


@app.post("/api/v1/auth/logout")
async def logout(request: Request, response: Response, db=Depends(get_db)):
    hashed = hashlib.sha256(request.cookies.get("adrobot_session", "").encode()).hexdigest()
    row = await db.get(LoginSession, hashed)
    if row:
        await db.delete(row)
        await db.commit()
    response.delete_cookie("adrobot_session")
    return {"ok": True}


@app.get("/api/v1/config", dependencies=auth)
async def config():
    cfg = settings()
    return {"mode": cfg.keitaro_mode, "keitaro_url": cfg.keitaro_url, "requires_login": bool(cfg.operator_password)}


@app.get("/api/v1/reference", dependencies=auth)
async def references():
    return await tracker().references()


@app.get("/api/v1/reference/countries", dependencies=auth)
async def countries():
    import pycountry
    return [{"code": x.alpha_2, "name": x.name} for x in sorted(pycountry.countries, key=lambda x: x.name)]


@app.get("/api/v1/offers", dependencies=auth)
async def offers(query: str = "", offset: int = 0, limit: int = 20):
    if offset < 0 or not 1 <= limit <= 100 or len(query) > 255:
        raise AppError("INVALID_QUERY", "Некорректные параметры поиска.")
    rows = [x for x in await tracker().offers() if query.casefold() in f"{x['id']} {x['name']}".casefold()]
    return {"items": [{"id": int(x["id"]), "name": x["name"]} for x in rows[offset:offset + limit]], "total": len(rows)}


@app.get("/api/v1/campaigns", dependencies=auth)
async def campaigns(db=Depends(get_db)):
    return [await svc.campaign_view(db, x) for x in (await db.scalars(select(Campaign).order_by(Campaign.synced_at.desc()))).all()]


@app.post("/api/v1/campaigns/import", dependencies=auth)
async def import_campaign(body: schema.ImportCampaign, db=Depends(get_db)):
    async with mutation_lock:
        return await svc.import_campaign(db, tracker(), body.remote_id)


@app.get("/api/v1/campaigns/{campaign_id}", dependencies=auth)
async def campaign(campaign_id: str, db=Depends(get_db)):
    row = await db.get(Campaign, campaign_id)
    if not row:
        raise AppError("NOT_FOUND", "Кампания не найдена.", 404)
    return await svc.campaign_view(db, row)


@app.post("/api/v1/campaigns/{campaign_id}/fetch", dependencies=auth)
async def fetch(campaign_id: str, db=Depends(get_db)):
    async with mutation_lock:
        row = await db.get(Campaign, campaign_id)
        if not row:
            raise AppError("NOT_FOUND", "Кампания не найдена.", 404)
        return await svc.import_campaign(db, tracker(), row.remote_id)


def valid_key(key):
    if not key or not 8 <= len(key) <= 128:
        raise AppError("IDEMPOTENCY_REQUIRED", "Передайте Idempotency-Key длиной от 8 до 128 символов.")
    return key


@app.post("/api/v1/campaigns", dependencies=auth, status_code=202)
async def create(body: schema.CreateCampaign, idempotency_key: str = Header(default=""), db=Depends(get_db)):
    async with mutation_lock:
        return await svc.create_campaign(db, tracker(), body, valid_key(idempotency_key))


@app.post("/api/v1/streams/{stream_id}/offers", dependencies=auth)
async def add(stream_id: str, body: schema.AddOffer, db=Depends(get_db)):
    async with mutation_lock:
        return await svc.edit(db, tracker(), stream_id, "add", body)


@app.post("/api/v1/streams/{stream_id}/offers/{link_id}/remove", dependencies=auth)
async def remove(stream_id: str, link_id: str, body: schema.Revision, db=Depends(get_db)):
    async with mutation_lock:
        return await svc.edit(db, tracker(), stream_id, "remove", body, link_id)


@app.post("/api/v1/streams/{stream_id}/offers/{link_id}/restore", dependencies=auth)
async def restore(stream_id: str, link_id: str, body: schema.Revision, db=Depends(get_db)):
    async with mutation_lock:
        return await svc.edit(db, tracker(), stream_id, "restore", body, link_id)


@app.patch("/api/v1/streams/{stream_id}/offers/{link_id}", dependencies=auth)
async def pin(stream_id: str, link_id: str, body: schema.PinOffer, db=Depends(get_db)):
    async with mutation_lock:
        return await svc.edit(db, tracker(), stream_id, "pin", body, link_id)


@app.post("/api/v1/streams/{stream_id}/cancel", dependencies=auth)
async def cancel(stream_id: str, body: schema.Revision, db=Depends(get_db)):
    async with mutation_lock:
        return await svc.edit(db, tracker(), stream_id, "cancel", body)


@app.post("/api/v1/streams/{stream_id}/push", dependencies=auth, status_code=202)
async def push(stream_id: str, body: schema.Revision, idempotency_key: str = Header(default=""), db=Depends(get_db)):
    async with mutation_lock:
        return await svc.push(db, tracker(), stream_id, body.expected_revision, valid_key(idempotency_key))


@app.get("/api/v1/operations", dependencies=auth)
async def operations(db=Depends(get_db)):
    return [svc.operation_view(x) for x in (await db.scalars(select(Operation).order_by(Operation.created_at.desc()).limit(30))).all()]


@app.get("/api/v1/operations/{operation_id}", dependencies=auth)
async def operation(operation_id: str, db=Depends(get_db)):
    row = await db.get(Operation, operation_id)
    if not row:
        raise AppError("NOT_FOUND", "Операция не найдена.", 404)
    return svc.operation_view(row)


@app.post("/api/v1/operations/{operation_id}/reconcile", dependencies=auth)
async def reconcile(operation_id: str, db=Depends(get_db)):
    async with mutation_lock:
        row = await db.get(Operation, operation_id)
        if not row:
            raise AppError("NOT_FOUND", "Операция не найдена.", 404)
        if row.status not in ("unknown", "running"):
            return svc.operation_view(row)
        if row.kind == "create":
            if "alias" not in row.data:
                row.status, row.error = "failed", "Операция прервана до записи в Keitaro. Создайте кампанию заново."
                await db.commit()
                return svc.operation_view(row)
            return await svc.resume_create(db, tracker(), row)
        return await svc.reconcile_push(db, tracker(), row)


@app.get("/api/v1/demo/remote/{remote_id}", dependencies=auth)
async def demo_remote(remote_id: int):
    if settings().keitaro_mode != "demo":
        raise AppError("NOT_FOUND", "Недоступно в рабочем режиме.", 404)
    return await tracker().streams(remote_id)


@app.post("/api/v1/demo/streams/{remote_id}/remove/{offer_id}", dependencies=auth)
async def demo_external_remove(remote_id: int, offer_id: int):
    if settings().keitaro_mode != "demo":
        raise AppError("NOT_FOUND", "Недоступно в рабочем режиме.", 404)
    async with mutation_lock:
        remote = tracker()
        stream = await remote.stream(remote_id)
        offers = [x for x in stream["offers"] if x["offer_id"] != offer_id]
        if not offers:
            raise AppError("LAST_OFFER", "Оставьте хотя бы один оффер в демотрекере.")
        base, extra = divmod(100, len(offers))
        for i, x in enumerate(offers):
            x["share"] = base + (i < extra)
        return await remote.update_offers(remote_id, offers)


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(db=Depends(get_db)):
    await db.execute(text("SELECT 1 FROM campaigns LIMIT 1"))
    return {"status": "ready", "mode": settings().keitaro_mode}
