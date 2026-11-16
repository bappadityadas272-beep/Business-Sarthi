"""SQLAlchemy models for ARCHITECTURE section 7. Keep SQL portable (SQLite now, PostgreSQL later)."""
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _fk(target: str):
    return mapped_column(ForeignKey(target, ondelete="CASCADE"), index=True)


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(8), default="hi")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    shops: Mapped[list["Shop"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    consents: Mapped[list["Consent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(cascade="all, delete-orphan")


class Consent(Base):
    __tablename__ = "consent"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = _fk("user.id")
    purpose: Mapped[str] = mapped_column(String(64))
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="consents")


class Shop(Base):
    __tablename__ = "shop"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = _fk("user.id")
    shop_type: Mapped[str] = mapped_column(String(32), default="kirana")
    name: Mapped[str | None] = mapped_column(String(80))            # DEC-42
    size_sqft: Mapped[float | None] = mapped_column(Float)          # DEC-42: ML2 feature, typed by the owner
    city_tier: Mapped[int | None] = mapped_column(Integer)          # DEC-42: 1, 2 or 3, picked by the owner
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    budget: Mapped[float] = mapped_column(Float)
    monthly_rent: Mapped[float] = mapped_column(Float)
    staff_count: Mapped[int] = mapped_column(Integer, default=0)
    launch_date: Mapped[date | None] = mapped_column(Date)
    is_demo: Mapped[bool] = mapped_column(default=False)
    user: Mapped[User] = relationship(back_populates="shops")
    daily_logs: Mapped[list["DailyLog"]] = relationship(cascade="all, delete-orphan")
    stock_items: Mapped[list["StockItem"]] = relationship(cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]] = relationship(cascade="all, delete-orphan")
    loans: Mapped[list["Loan"]] = relationship(cascade="all, delete-orphan")
    forecasts: Mapped[list["Forecast"]] = relationship(cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship(cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(cascade="all, delete-orphan")


class DailyLog(Base):
    __tablename__ = "daily_log"
    __table_args__ = (UniqueConstraint("shop_id", "day", "category", name="uq_daily_log_shop_day_cat"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    day: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(32))
    sales: Mapped[float] = mapped_column(Float, default=0.0)
    purchases: Mapped[float] = mapped_column(Float, default=0.0)
    expenses: Mapped[float] = mapped_column(Float, default=0.0)


class Forecast(Base):
    __tablename__ = "forecast"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    kind: Mapped[str] = mapped_column(String(16))  # setup | reforecast
    made_on: Mapped[date] = mapped_column(Date)
    horizon_months: Mapped[list] = mapped_column(JSON)
    drivers: Mapped[list] = mapped_column(JSON, default=list)


class Review(Base):
    __tablename__ = "review"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    decision: Mapped[str] = mapped_column(String(8))  # grow | hold | pivot
    indicators: Mapped[dict] = mapped_column(JSON)
    reasons: Mapped[list] = mapped_column(JSON)
    actions: Mapped[list] = mapped_column(JSON)


class Loan(Base):
    __tablename__ = "loan"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    principal: Mapped[float] = mapped_column(Float)
    emi: Mapped[float] = mapped_column(Float)
    due_day: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)           # DEC-53
    tenure_months: Mapped[int | None] = mapped_column(Integer)      # DEC-53: number of monthly instalments


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))  # info | warn | critical
    message_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved: Mapped[bool] = mapped_column(default=False)


class StockItem(Base):
    __tablename__ = "stock_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    name: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(16))
    cost: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    reorder_point: Mapped[float | None] = mapped_column(Float)
    moves: Mapped[list["StockMove"]] = relationship(cascade="all, delete-orphan")


class StockMove(Base):
    __tablename__ = "stock_move"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = _fk("stock_item.id")
    day: Mapped[date] = mapped_column(Date)
    qty: Mapped[float] = mapped_column(Float)  # positive = in, negative = out
    kind: Mapped[str] = mapped_column(String(16))  # purchase | sale | adjust | waste


class Asset(Base):
    __tablename__ = "asset"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    name: Mapped[str] = mapped_column(String(64))
    cost: Mapped[float] = mapped_column(Float)
    bought_on: Mapped[date | None] = mapped_column(Date)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = _fk("shop.id")
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    sources_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = _fk("user.id")
    kind: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    read: Mapped[bool] = mapped_column(default=False)


class OsmCache(Base):
    """Overpass answers per rounded cell, kept 30 days (M-01). Holds no personal data."""
    __tablename__ = "osm_cache"
    __table_args__ = (UniqueConstraint("cell", "radius_m", "tags_version", name="uq_osm_cache_cell"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cell: Mapped[str] = mapped_column(String(32))           # "lat,lon" rounded (data/rules/osm_tags.yaml)
    radius_m: Mapped[int]
    tags_version: Mapped[int]
    counts: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


EXPECTED_TABLES = {
    "user", "consent", "shop", "daily_log", "forecast", "review", "loan", "alert",
    "stock_item", "stock_move", "asset", "chat_message", "notification", "osm_cache",
}
