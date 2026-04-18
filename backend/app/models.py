"""SQLAlchemy ORM models: Listing, PlzGeodata, User, SavedSearch, SearchNotification."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column



class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[str | None] = mapped_column(String, nullable=True)
    price_numeric: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    condition: Mapped[str | None] = mapped_column(String, nullable=True)
    shipping: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    images: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    author: Mapped[str] = mapped_column(String, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    plz: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_sold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="rcnetwork", index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, server_default="flugmodelle", index=True)

    # --- LLM-extracted analysis fields (Step 014) ---
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    drive_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_subtype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    completeness: Mapped[str | None] = mapped_column(String(30), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    llm_analyzed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    price_indicator: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_indicator_median: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_indicator_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipping_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class PlzGeodata(Base):
    __tablename__ = "plz_geodata"

    plz: Mapped[str] = mapped_column(String(5), primary_key=True)
    city: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)


class IntlGeodata(Base):
    __tablename__ = "intl_geodata"

    country: Mapped[str] = mapped_column(String(2), primary_key=True)
    plz: Mapped[str] = mapped_column(String(10), primary_key=True)
    city: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    google_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    is_approved: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    search: Mapped[str | None] = mapped_column(String(255))
    plz: Mapped[str | None] = mapped_column(String(10))
    max_distance: Mapped[int | None] = mapped_column(Integer)
    sort: Mapped[str] = mapped_column(String(20), server_default="date")
    sort_dir: Mapped[str] = mapped_column(String(4), server_default="desc")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SearchNotification(Base):
    __tablename__ = "search_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    saved_search_id: Mapped[int] = mapped_column(
        ForeignKey("saved_searches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("saved_search_id", "listing_id", name="uq_search_listing"),
    )


class UserFavorite(Base):
    __tablename__ = "user_favorites"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
