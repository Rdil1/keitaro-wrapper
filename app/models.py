from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CreatedCampaign(Base):
    """Кампании, созданные через «создаватор». Источник правды — Keitaro, здесь локальный учёт."""

    __tablename__ = "created_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geo: Mapped[str] = mapped_column(String(512))  # коды стран через запятую: MX,AU,RO
    offer_id: Mapped[int] = mapped_column(Integer)
    geo_stream_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offer_stream_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OfferChange(Base):
    """История изменений состава офферов в потоках."""

    __tablename__ = "offer_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(16))  # add | remove | restore | edit | push | discard …
    offers_before: Mapped[list] = mapped_column(JSON)
    offers_after: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StreamOffer(Base):
    """Черновик состава офферов потока в обёртке.

    status:
      live     — оффер есть в Keitaro;
      new      — добавлен в обёртке, ещё не запушен;
      removing — удалён в обёртке, в Keitaro ещё есть до пуша;
      archived — удалён из Keitaro пушем, хранится в обёртке, можно вернуть.
    pushed_share / pushed_state — что лежит в Keitaro после последнего пуша (для live и removing).
    """

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_stream_offers_stream_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[int] = mapped_column(Integer, index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0)
    share: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(16), default="active")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="live")
    pushed_share: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pushed_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
