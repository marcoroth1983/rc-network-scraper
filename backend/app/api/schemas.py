"""Pydantic response models for the API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.config import CATEGORY_KEYS


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
    category: str = "flugmodelle"
    # LLM-extracted product fields
    manufacturer: str | None = None
    model_name: str | None = None
    model_type: str | None = None
    model_subtype: str | None = None
    drive_type: str | None = None
    completeness: str | None = None
    shipping_available: bool | None = None
    price_indicator: str | None = None
    price_indicator_median: float | None = None
    price_indicator_count: int | None = None


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
    category: str = "flugmodelle"
    # LLM-extracted product fields
    manufacturer: str | None = None
    model_name: str | None = None
    model_type: str | None = None
    model_subtype: str | None = None
    drive_type: str | None = None
    completeness: str | None = None
    attributes: dict[str, str] = {}
    shipping_available: bool | None = None
    price_indicator: str | None = None
    price_indicator_median: float | None = None
    price_indicator_count: int | None = None


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
    cleaned_sold: int = 0
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


class SavedSearchCreate(BaseModel):
    search: str | None = None
    plz: str | None = None
    max_distance: int | None = None
    sort: Literal["date", "price", "distance"] = "date"
    sort_dir: Literal["asc", "desc"] = "desc"
    category: str | None = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORY_KEYS:
            raise ValueError(f"Unknown category: '{v}'")
        return v

    @model_validator(mode="after")
    def validate_distance_requires_plz(self) -> "SavedSearchCreate":
        if self.max_distance is not None and self.plz is None:
            raise ValueError("max_distance requires plz to be set")
        return self


class SavedSearchUpdate(BaseModel):
    search: str | None = None
    plz: str | None = None
    max_distance: int | None = None
    sort: Literal["date", "price", "distance"] = "date"
    sort_dir: Literal["asc", "desc"] = "desc"
    category: str | None = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORY_KEYS:
            raise ValueError(f"Unknown category: '{v}'")
        return v

    @model_validator(mode="after")
    def validate_distance_requires_plz(self) -> "SavedSearchUpdate":
        if self.max_distance is not None and self.plz is None:
            raise ValueError("max_distance requires plz to be set")
        return self


class SavedSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str | None
    search: str | None
    plz: str | None
    max_distance: int | None
    sort: str
    sort_dir: str
    is_active: bool
    category: str | None = None
    last_checked_at: datetime | None
    last_viewed_at: datetime | None
    created_at: datetime
    match_count: int = 0
