import hashlib
import json
from copy import deepcopy
from uuid import uuid4
from sqlalchemy import select
from .errors import AppError
from .models import Campaign, Stream, OfferLink, Operation, now
from .weights import recalculate


def fingerprint(data):
    """Ignore tracker timestamps/association IDs, retain routing settings and offer states."""
    fields = ("schema", "type", "state", "position", "action_type", "action_payload", "filters", "landings")
    payload = {k: data.get(k) for k in fields}
    payload["offers"] = sorted([{"offer_id": int(x["offer_id"]), "share": int(x["share"]),
                                  "state": x.get("state", "active")} for x in data.get("offers", [])], key=lambda x: x["offer_id"])
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(links):
    return sorted([{"offer_id": x.offer_id, "active": x.active, "share": x.share,
                    "pinned": x.pinned, "position": x.position, "remote_state": x.remote_state} for x in links],
                  key=lambda x: x["offer_id"])


async def get_stream(db, stream_id):
    row = await db.get(Stream, stream_id)
    if not row:
        raise AppError("NOT_FOUND", "Поток не найден.", 404)
    return row


async def links_for(db, stream_id):
    return list((await db.scalars(select(OfferLink).where(OfferLink.stream_id == stream_id).order_by(OfferLink.position, OfferLink.offer_id))).all())


async def stream_view(db, stream):
    links = await links_for(db, stream.id)
    old = {x["offer_id"]: x for x in stream.published}
    return {"id": stream.id, "remote_id": stream.remote_id, "name": stream.name, "position": stream.position,
            "revision": stream.revision, "editable": stream.editable, "missing": stream.missing,
            "dirty": snapshot(links) != stream.published, "busy_operation": stream.busy_operation,
            "synced_at": stream.synced_at,
            "offers": [{"id": x.id, "offer_id": x.offer_id, "name": x.name, "active": x.active,
                        "share": x.share, "pinned": x.pinned,
                        "published_active": old.get(x.offer_id, {}).get("active", False),
                        "new": x.offer_id not in old, "remote_state": x.remote_state} for x in links]}


async def campaign_view(db, campaign):
    streams = (await db.scalars(select(Stream).where(Stream.campaign_id == campaign.id).order_by(Stream.position))).all()
    views = [await stream_view(db, x) for x in streams]
    return {"id": campaign.id, "remote_id": campaign.remote_id, "name": campaign.name,
            "config": {k: campaign.config.get(k) for k in ("alias", "domain_id", "group_id", "traffic_source_id", "type", "state")},
            "synced_at": campaign.synced_at, "streams": views}


async def import_campaign(db, remote, remote_id):
    existing = await db.scalar(select(Campaign).where(Campaign.remote_id == remote_id))
    if existing:
        for s in (await db.scalars(select(Stream).where(Stream.campaign_id == existing.id))).all():
            if s.busy_operation:
                raise AppError("OPERATION_PENDING", "Сначала выполните сверку незавершённой операции.", 409)
            if snapshot(await links_for(db, s.id)) != s.published:
                raise AppError("DRAFT_EXISTS", "Сначала опубликуйте или отмените черновики.", 409)
    await db.commit()
    # Retrieve everything before applying any changes locally.
    campaign_data = await remote.campaign(remote_id)
    remote_streams = await remote.streams(remote_id)
    offers = {int(x["id"]): x["name"] for x in await remote.offers()}
    if len({int(x["id"]) for x in remote_streams}) != len(remote_streams):
        raise AppError("KEITARO_SCHEMA", "В ответе Keitaro повторяются потоки.", 502)
    campaign = existing or Campaign(remote_id=remote_id, name=campaign_data["name"])
    db.add(campaign)
    campaign.name, campaign.config, campaign.synced_at = campaign_data["name"], campaign_data, now()
    await db.flush()
    local = {x.remote_id: x for x in (await db.scalars(select(Stream).where(Stream.campaign_id == campaign.id))).all()}
    present = set()
    for raw in remote_streams:
        rid = int(raw["id"])
        present.add(rid)
        s = local.get(rid)
        if not s:
            s = Stream(campaign_id=campaign.id, remote_id=rid, name=raw["name"])
            db.add(s)
            await db.flush()
        s.name, s.position, s.missing, s.synced_at = raw["name"], raw.get("position", 0), False, now()
        rows = await links_for(db, s.id)
        by_id = {x.offer_id: x for x in rows}
        incoming = raw.get("offers") or []
        if len({int(x["offer_id"]) for x in incoming}) != len(incoming):
            raise AppError("KEITARO_SCHEMA", "В потоке повторяются офферы. Импорт отменён.", 502)
        incoming_ids = set()
        for i, item in enumerate(incoming):
            oid, share = int(item["offer_id"]), int(item["share"])
            if not 0 <= share <= 100:
                raise AppError("KEITARO_SCHEMA", "Доли Keitaro вне диапазона 0…100.", 502)
            incoming_ids.add(oid)
            link = by_id.get(oid)
            if not link:
                link = OfferLink(stream_id=s.id, offer_id=oid, name=offers.get(oid, f"Offer #{oid}"),
                                 position=max([x.position for x in rows], default=-1) + 1, pinned=False)
                db.add(link)
                rows.append(link)
            elif link.share != share or not link.active:
                link.pinned = False
            link.name, link.active, link.share = offers.get(oid, link.name), True, share
            link.remote_state = item.get("state", "active")
        for link in rows:
            if link.offer_id not in incoming_ids:
                link.active, link.share, link.pinned = False, 0, False
        s.editable = bool(incoming) or bool(rows)
        s.remote_snapshot, s.published = deepcopy(raw), snapshot(rows)
        s.revision += 1
    for rid, s in local.items():
        if rid not in present:
            s.missing, s.revision = True, s.revision + 1
    await db.commit()
    return await campaign_view(db, campaign)


async def edit(db, remote, stream_id, action, body, link_id=None):
    s = await get_stream(db, stream_id)
    if s.revision != body.expected_revision:
        raise AppError("STALE_REVISION", "Поток изменился. Обновите данные и повторите действие.", 409)
    if s.busy_operation or s.missing or not s.editable:
        raise AppError("STREAM_LOCKED", "Этот поток сейчас недоступен для редактирования.", 409)
    rows = await links_for(db, s.id)
    if action == "cancel":
        old = {x["offer_id"]: x for x in s.published}
        for link in rows:
            if link.offer_id not in old:
                await db.delete(link)
            else:
                for key, value in old[link.offer_id].items():
                    setattr(link, key, value)
    else:
        if action == "add":
            found = next((x for x in await remote.offers() if int(x["id"]) == body.offer_id), None)
            if not found:
                raise AppError("OFFER_NOT_FOUND", "Оффер отсутствует в доступном каталоге Keitaro.")
            link = next((x for x in rows if x.offer_id == body.offer_id), None)
            if link and link.active:
                raise AppError("DUPLICATE_OFFER", "Этот оффер уже добавлен.", 409)
            if not link:
                link = OfferLink(stream_id=s.id, offer_id=body.offer_id, name=found["name"], active=True,
                                 share=0, pinned=False, position=max([x.position for x in rows], default=-1) + 1,
                                 remote_state="active")
                db.add(link)
                rows.append(link)
            link.active, link.pinned, link.remote_state = True, False, "active"
        else:
            link = next((x for x in rows if x.id == link_id), None)
            if not link:
                raise AppError("NOT_FOUND", "Связь оффера не найдена.", 404)
            if action == "remove":
                link.active, link.pinned, link.share = False, False, 0
                if not any(x["offer_id"] == link.offer_id for x in s.published):
                    await db.delete(link)
                    rows.remove(link)
            elif action == "restore":
                if link.active:
                    raise AppError("ALREADY_ACTIVE", "Оффер уже активен.", 409)
                if not any(int(x["id"]) == link.offer_id for x in await remote.offers()):
                    raise AppError("OFFER_NOT_FOUND", "Оффер больше не доступен в Keitaro.")
                link.active, link.pinned, link.remote_state = True, False, "active"
            elif action == "pin":
                if not link.active:
                    raise AppError("REMOVED_OFFER", "Нельзя закрепить удалённый оффер.")
                link.pinned = body.pinned
                if body.pinned and body.share is not None:
                    link.share = body.share
        recalculate(rows)
    s.revision += 1
    await db.commit()
    return await stream_view(db, s)


def operation_view(op):
    return {"id": op.id, "kind": op.kind, "status": op.status, "step": op.step, "error": op.error,
            "created_at": op.created_at, "updated_at": op.updated_at, "data": op.data}


async def operation(db, key, kind, request):
    op = await db.scalar(select(Operation).where(Operation.key == key))
    if op:
        if op.kind != kind or op.request != request:
            raise AppError("IDEMPOTENCY_CONFLICT", "Этот ключ уже использован для другого запроса.", 409)
        return op, False
    op = Operation(key=key, kind=kind, request=request, data={})
    db.add(op)
    await db.commit()
    return op, True


async def save_step(db, op, step, **data):
    op.step, op.data, op.updated_at = step, {**op.data, **data}, now()
    await db.commit()


async def fail_operation(db, op, exc):
    operation_id = op.id
    await db.rollback()
    op = await db.get(Operation, operation_id)
    op.status, op.error, op.updated_at = "unknown", str(exc)[:500], now()
    await db.commit()
    return operation_view(op)


async def create_campaign(db, remote, body, key):
    request = body.model_dump()
    op, fresh = await operation(db, key, "create", request)
    if not fresh:
        return operation_view(op)
    try:
        refs = await remote.references()
        for kind, field in [("domains", "domain_id"), ("groups", "group_id"), ("traffic_sources", "traffic_source_id")]:
            if not any(int(x["id"]) == request[field] for x in refs[kind]):
                raise AppError("INVALID_REFERENCE", "Выбранная настройка кампании отсутствует в Keitaro.")
        if not any(int(x["id"]) == body.offer_id for x in await remote.offers()):
            raise AppError("OFFER_NOT_FOUND", "Оффер не найден в Keitaro.")
        await save_step(db, op, "validated", alias=f"adrobot-{op.id[:18]}")
        return await resume_create(db, remote, op, initial=True)
    except Exception as exc:
        # No network mutation was started before validation; safe to mark failed.
        if op.step == "start":
            op.status, op.error = "failed", str(exc)[:500]
            await db.commit()
            if isinstance(exc, AppError):
                raise exc
        return await fail_operation(db, op, exc)


async def resume_create(db, remote, op, initial=False):
    data = op.request
    try:
        alias = op.data["alias"]
        rid = op.data.get("remote_id")
        if not rid:
            matches = [x for x in await remote.campaigns() if x.get("alias") == alias]
            if matches:
                rid = int(matches[0]["id"])
            elif initial or op.step == "validated":
                await save_step(db, op, "campaign_request_started")
                created = await remote.create_campaign({"name": data["name"], "alias": alias, "state": "disabled",
                                                       "type": "position", "domain_id": data["domain_id"],
                                                       "group_id": str(data["group_id"]), "traffic_source_id": data["traffic_source_id"]})
                rid = int(created["id"])
            else:
                raise AppError("RESULT_UNKNOWN", "Кампания с alias операции пока не найдена. Проверьте Keitaro и повторите сверку позже.", 409)
            await save_step(db, op, "campaign_created", remote_id=rid)
        existing = await remote.streams(rid)
        expected = [
            {"campaign_id": rid, "name": "GEO → Google", "position": 1, "type": "regular", "schema": "redirect",
             "state": "active", "action_type": "http", "action_payload": "https://google.com/", "collect_clicks": True,
             "filters": [{"name": "country", "mode": "accept", "payload": [data["geo_code"]]}]},
            {"campaign_id": rid, "name": "Offers", "position": 2, "type": "regular", "schema": "landings",
             "state": "active", "action_type": "http", "collect_clicks": True, "landings": [],
             "offers": [{"offer_id": data["offer_id"], "share": 100, "state": "active"}]},
        ]
        for index, payload in enumerate(expected):
            matches = [x for x in existing if x["name"] == payload["name"] and x.get("position") == payload["position"]]
            if not matches:
                if not initial and op.step == f"stream_{index}_request_started":
                    raise AppError("RESULT_UNKNOWN", "Ответ создания потока неизвестен. Проверьте трекер и повторите сверку.", 409)
                await save_step(db, op, f"stream_{index}_request_started")
                await remote.create_stream(payload)
                await save_step(db, op, f"stream_{index}_created")
        verified = await remote.streams(rid)
        if len(verified) != 2:
            raise AppError("CREATE_MISMATCH", "Созданная кампания не содержит ровно два ожидаемых потока.", 502)
        geo = next((x for x in verified if x.get("position") == 1), {})
        offer = next((x for x in verified if x.get("position") == 2), {})
        if (geo.get("action_payload") != "https://google.com/" or geo.get("schema") != "redirect"
                or not any(x.get("name") == "country" and x.get("mode") == "accept" and x.get("payload") == [data["geo_code"]] for x in geo.get("filters", []))
                or offer.get("offers", []) == [] or len(offer["offers"]) != 1
                or int(offer["offers"][0]["offer_id"]) != data["offer_id"] or int(offer["offers"][0]["share"]) != 100):
            raise AppError("CREATE_MISMATCH", "Настройки созданных потоков не совпали с заданием.", 502)
        await remote.activate(rid)
        config = await remote.campaign(rid)
        if config.get("type") != "position" or config.get("state") != "active" or any(str(config.get(k)) != str(data[k]) for k in ("domain_id", "group_id", "traffic_source_id")):
            raise AppError("CREATE_MISMATCH", "Keitaro не подтвердил настройки кампании.", 502)
        campaign = await import_campaign(db, remote, rid)
        op.status, op.error = "succeeded", None
        await save_step(db, op, "done", campaign_id=campaign["id"])
        return operation_view(op)
    except Exception as exc:
        return await fail_operation(db, op, exc)


async def push(db, remote, stream_id, revision, key):
    op, fresh = await operation(db, key, "push", {"stream_id": stream_id, "expected_revision": revision})
    if not fresh:
        return operation_view(op)
    s = await get_stream(db, stream_id)
    if s.revision != revision or s.busy_operation or s.missing:
        op.status, op.error = "failed", "Конфликт состояния потока"
        await db.commit()
        raise AppError("STALE_REVISION", "Поток изменился или ожидает сверки.", 409)
    rows = await links_for(db, s.id)
    active = [x for x in rows if x.active]
    if not s.editable or not active or sum(x.share for x in active) != 100:
        op.status, op.error = "failed", "Недопустимые доли"
        await db.commit()
        raise AppError("INVALID_SHARES", "Перед публикацией сумма активных долей должна быть 100%.")
    target = [{"offer_id": x.offer_id, "share": x.share, "state": x.remote_state} for x in active]
    s.busy_operation = op.id
    await save_step(db, op, "checking", stream_id=s.id, remote_id=s.remote_id, target=target,
                    local_snapshot=snapshot(rows), before=s.remote_snapshot)
    try:
        current = await remote.stream(s.remote_id)
        if fingerprint(current) != fingerprint(s.remote_snapshot):
            op.status, op.error, s.busy_operation = "conflict", "Поток изменён в Keitaro. Черновик сохранён. Для обновления отмените его и выполните Fetch.", None
            await db.commit()
            return operation_view(op)
        catalog = {int(x["id"]) for x in await remote.offers()}
        if any(x.offer_id not in catalog for x in active):
            raise AppError("OFFER_NOT_FOUND", "Один из активных офферов больше не доступен.")
        await save_step(db, op, "write_started")
        await remote.update_offers(s.remote_id, target)
        return await reconcile_push(db, remote, op)
    except Exception as exc:
        return await fail_operation(db, op, exc)


async def reconcile_push(db, remote, op):
    try:
        s = await get_stream(db, op.data["stream_id"])
        current = await remote.stream(s.remote_id)
        target = {**op.data["before"], "offers": op.data["target"]}
        if fingerprint(current) == fingerprint(target):
            s.remote_snapshot, s.published, s.busy_operation = current, op.data["local_snapshot"], None
            s.synced_at, s.revision = now(), s.revision + 1
            op.status, op.error = "succeeded", None
            await save_step(db, op, "done")
        elif fingerprint(current) == fingerprint(op.data["before"]):
            # A later explicit Push may safely retry against the unchanged base.
            s.busy_operation, op.status = None, "failed"
            op.error = "Изменения не применены в Keitaro. Черновик сохранён, можно повторить Push."
            await db.commit()
        else:
            s.busy_operation, op.status = None, "conflict"
            op.error = "В Keitaro обнаружено другое состояние. Отмените черновик и выполните Fetch перед повторным редактированием."
            await db.commit()
        return operation_view(op)
    except Exception as exc:
        return await fail_operation(db, op, exc)
