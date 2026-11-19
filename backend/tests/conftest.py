import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app import db, main, keitaro
from app.models import Base


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    session = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "Session", session)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "Session", session)
    monkeypatch.setattr(keitaro, "Session", session)
    monkeypatch.setattr(main, "mutation_lock", asyncio.Lock())
    monkeypatch.setattr(main.settings(), "keitaro_mode", "demo")
    monkeypatch.setattr(main.settings(), "operator_password", "")

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    asyncio.run(setup())
    with TestClient(main.app, headers={"X-Requested-With": "Adrobot"}) as c:
        yield c
