"""Keitaro Admin API v1 adapter and an isolated, persistent demonstration tracker."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import httpx
from sqlalchemy import select
from .config import settings
from .db import Session
from .models import DemoResource
from .errors import AppError


DEMO_OFFERS = [
    {"id": 3749, "name": "Miaflow · Beauty RO · Spin", "state": "active"},
    {"id": 3717, "name": "Miaflow · Beauty RO · Prize", "state": "active"},
    {"id": 11111, "name": "FitoMishki · Wellness ES", "state": "active"},
    {"id": 11112, "name": "Oxys · Beauty CL", "state": "active"},
    {"id": 4821, "name": "Nutra Balance · Australia", "state": "active"},
    {"id": 4822, "name": "Daily Care · Mexico", "state": "active"},
]
DEMO_REFS = {
    "domains": [{"id": 1, "name": "https://track.example.test"}],
    "groups": [{"id": 1, "name": "FORTESTS"}],
    "traffic_sources": [{"id": 1, "name": "FORTESTS"}],
}


class KeitaroClient:
    def __init__(self):
        cfg = settings()
        self.url = cfg.keitaro_url.rstrip("/")
        if self.url.endswith("/admin_api/v1"):
            self.url = self.url[:-13]
        self.key = cfg.keitaro_api_key

    async def request(self, method, path, **kwargs):
        timeout = httpx.Timeout(20, connect=5)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for attempt in range(3 if method == "GET" else 1):
                try:
                    response = await client.request(method, f"{self.url}/admin_api/v1{path}",
                                                    headers={"Api-Key": self.key}, **kwargs)
                except httpx.TimeoutException:
                    if method == "GET" and attempt < 2:
                        await asyncio.sleep(.3 * (attempt + 1))
                        continue
                    raise AppError("KEITARO_TIMEOUT", "Keitaro не ответил вовремя. Результат записи требует сверки.", 504)
                except httpx.RequestError:
                    if method == "GET" and attempt < 2:
                        await asyncio.sleep(.3 * (attempt + 1))
                        continue
                    raise AppError("KEITARO_UNAVAILABLE", "Не удалось подключиться к Keitaro.", 503)
                if method == "GET" and response.status_code in (429, 502, 503, 504) and attempt < 2:
                    try:
                        delay = min(float(response.headers.get("Retry-After", "1")), 5)
                    except ValueError:
                        delay = 1
                    await asyncio.sleep(max(delay, 0))
                    continue
                if response.is_error:
                    # Do not reflect arbitrary upstream text (it can contain secrets or HTML).
                    raise AppError("KEITARO_ERROR", f"Keitaro отклонил запрос (HTTP {response.status_code}). Проверьте доступ и настройки API.",
                                   502, upstream_status=response.status_code)
                try:
                    return response.json()
                except ValueError:
                    raise AppError("KEITARO_SCHEMA", "Keitaro вернул ответ не в формате JSON.", 502)

    async def items(self, path, **params):
        # Public v1 spec: only campaigns support offset/limit; other resources return complete arrays.
        if path != "/campaigns":
            rows = await self.request("GET", path, params=params)
            if not isinstance(rows, list):
                raise AppError("KEITARO_SCHEMA", "Неожиданный формат списка Keitaro; импорт отменён.", 502)
            return rows
        result, seen = [], set()
        for offset in range(0, 100000, 200):
            rows = await self.request("GET", path, params={**params, "offset": offset, "limit": 200})
            if not isinstance(rows, list):
                raise AppError("KEITARO_SCHEMA", "Неполный список кампаний Keitaro.", 502)
            if any(x["id"] in seen for x in rows):
                raise AppError("KEITARO_PAGINATION", "Keitaro повторяет страницы. Синхронизация остановлена.", 502)
            result.extend(rows)
            seen.update(x["id"] for x in rows)
            if len(rows) < 200:
                return result
        raise AppError("KEITARO_PAGINATION", "Превышен лимит страниц Keitaro.", 502)

    async def references(self):
        domains, groups, sources = await asyncio.gather(
            self.items("/domains"), self.items("/groups", type="campaigns"), self.items("/traffic_sources"))
        return {"domains": domains, "groups": groups, "traffic_sources": sources}

    async def offers(self):
        return [x for x in await self.items("/offers") if x.get("state") != "deleted"]

    async def campaign(self, remote_id):
        return await self.request("GET", f"/campaigns/{remote_id}")

    async def campaigns(self):
        return await self.items("/campaigns")

    async def streams(self, remote_id):
        return await self.items(f"/campaigns/{remote_id}/streams")

    async def stream(self, remote_id):
        return await self.request("GET", f"/streams/{remote_id}")

    async def create_campaign(self, data):
        return await self.request("POST", "/campaigns", json=data)

    async def create_stream(self, data):
        return await self.request("POST", "/streams", json=data)

    async def activate(self, remote_id):
        return await self.request("PUT", f"/campaigns/{remote_id}", json={"state": "active"})

    async def update_offers(self, remote_id, offers):
        return await self.request("PUT", f"/streams/{remote_id}", json={"offers": offers})


class DemoKeitaro:
    async def all(self, kind):
        async with Session() as db:
            rows = (await db.scalars(select(DemoResource).where(DemoResource.kind == kind))).all()
            return [deepcopy(x.data) for x in rows]

    async def get(self, kind, remote_id):
        async with Session() as db:
            row = await db.get(DemoResource, f"{kind}:{remote_id}")
            if not row:
                raise AppError("KEITARO_NOT_FOUND", "Объект отсутствует в демотрекере.", 404)
            return deepcopy(row.data)

    async def save(self, kind, data):
        async with Session() as db:
            key = f"{kind}:{data['id']}"
            row = await db.get(DemoResource, key)
            if row:
                row.data = deepcopy(data)
            else:
                db.add(DemoResource(id=key, kind=kind, data=deepcopy(data)))
            await db.commit()
        return deepcopy(data)

    async def references(self):
        return deepcopy(DEMO_REFS)

    async def offers(self):
        return deepcopy(DEMO_OFFERS)

    async def campaigns(self):
        return await self.all("campaign")

    async def campaign(self, remote_id):
        return await self.get("campaign", remote_id)

    async def streams(self, remote_id):
        return sorted([x for x in await self.all("stream") if x["campaign_id"] == remote_id], key=lambda x: x["position"])

    async def stream(self, remote_id):
        return await self.get("stream", remote_id)

    async def create_campaign(self, data):
        return await self.save("campaign", {**data, "id": uuid4().int % 1_000_000_000})

    async def create_stream(self, data):
        return await self.save("stream", {"offers": [], "landings": [], "filters": [], **data, "id": uuid4().int % 1_000_000_000})

    async def activate(self, remote_id):
        return await self.save("campaign", {**await self.campaign(remote_id), "state": "active"})

    async def update_offers(self, remote_id, offers):
        return await self.save("stream", {**await self.stream(remote_id), "offers": deepcopy(offers)})


def tracker():
    return DemoKeitaro() if settings().keitaro_mode == "demo" else KeitaroClient()


async def seed_demo():
    remote = DemoKeitaro()
    if await remote.campaigns():
        return
    await remote.save("campaign", {"id": 93212, "name": "Beauty · Romania / Q4", "alias": "beauty-ro",
                                      "domain_id": 1, "group_id": 1, "traffic_source_id": 1,
                                      "type": "position", "state": "active"})
    await remote.save("stream", {"id": 564220, "campaign_id": 93212, "name": "GEO → Google", "position": 1,
                                   "schema": "redirect", "type": "regular", "state": "active", "action_type": "http",
                                   "action_payload": "https://google.com/", "offers": [], "landings": [],
                                   "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}]})
    await remote.save("stream", {"id": 564221, "campaign_id": 93212, "name": "Offers", "position": 2,
                                   "schema": "landings", "type": "regular", "state": "active", "action_type": "http",
                                   "offers": [{"offer_id": 3749, "share": 34, "state": "active"},
                                              {"offer_id": 3717, "share": 33, "state": "active"},
                                              {"offer_id": 11111, "share": 33, "state": "active"}], "filters": [], "landings": []})
