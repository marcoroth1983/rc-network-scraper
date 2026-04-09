"""Pydantic response models for the API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ListingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    url: str
    title: str
    price: str | None
    price_numeric: float | None = None
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
    is_favorite: bool = False


class ListingDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    url: str
    title: str
    price: str | None
    price_numeric: float | None = None
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
    is_favorite: bool = False


class PlzResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plz: str
    city: str
    lat: float
    lon: float


class ScrapeSummary(BaseModel):
    pages_crawled: int = 0
    new: int = 0
    updated: int = 0
    rechecked: int = 0
    sold_found: int = 0
    deleted_sold: int = 0
    deleted_stale: int = 0


class ScrapeStatus(BaseModel):
    status: Literal["idle", "running", "done", "error"]
    job_type: Literal["update", "regular"] | None = None
    started_at: str | None = None
    finished_at: str | None = None
    phase: Literal["phase1", "phase2", "phase3"] | None = None
    progress: str | None = None
    summary: ScrapeSummary | None = None
    error: str | None = None


class ScrapeLogEntry(BaseModel):
    job_type: Literal["update", "regular"]
    finished_at: str
    summary: ScrapeSummary | None = None
    error: str | None = None


class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[ListingSummary]
