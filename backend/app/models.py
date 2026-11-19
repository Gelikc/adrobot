from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    remote_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[str] = mapped_column(String(40), default=now)


class Stream(Base):
    __tablename__ = "streams"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    remote_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(default=0)
    revision: Mapped[int] = mapped_column(default=1)
    editable: Mapped[bool] = mapped_column(Boolean, default=False)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    busy_operation: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published: Mapped[list] = mapped_column(JSON, default=list)
    remote_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[str] = mapped_column(String(40), default=now)


class OfferLink(Base):
    __tablename__ = "stream_offer_links"
    __table_args__ = (
        UniqueConstraint("stream_id", "offer_id"),
        CheckConstraint("share >= 0 AND share <= 100"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    stream_id: Mapped[str] = mapped_column(ForeignKey("streams.id"), index=True)
    offer_id: Mapped[int]
    name: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(default=0)
    remote_state: Mapped[str] = mapped_column(String(20), default="active")


class Operation(Base):
    __tablename__ = "integration_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="running")
    step: Mapped[str] = mapped_column(String(60), default="start")
    request: Mapped[dict] = mapped_column(JSON)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class DemoResource(Base):
    """Durable fake tracker, separate from local draft/published tables."""
    __tablename__ = "demo_keitaro_resources"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    data: Mapped[dict] = mapped_column(JSON)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[int]
