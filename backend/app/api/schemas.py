"""Pydantic response models for the API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ListingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    url: str
    title: str
    price: str | None
    condition: str | None
    plz: str | None
    city: str | None
    latitude: float | None
    longitude: float | None
    author: str
    posted_at: datetime | None
    scraped_at: datetime
    distance_km: float | None = None  # populated only when ?plz is provided
    images: list[str] = []
    is_sold: bool = False


class ListingDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    url: str
    title: str
    price: str | None
    condition: str | None
    shipping: str | None
    description: str
    images: list[str]
    tags: list[str] = []
    author: str
    posted_at: datetime | None
    posted_at_raw: str | None
    plz: str | None
    city: str | None
    latitude: float | None
    longitude: float | None
    scraped_at: datetime
    is_sold: bool


class PlzResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plz: str
    city: str
    lat: float
    lon: float


class ScrapeSummary(BaseModel):
    pages_crawled: int
    listings_found: int
    new: int
    updated: int
    skipped: int


class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[ListingSummary]
