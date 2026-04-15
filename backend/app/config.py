"""Application configuration via pydantic-settings."""

from dataclasses import dataclass

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    url: str


CATEGORIES: list[Category] = [
    Category("flugmodelle",    "Flugmodelle",               "https://www.rc-network.de/forums/biete-flugmodelle.132/"),
    Category("schiffsmodelle", "Schiffsmodelle",            "https://www.rc-network.de/forums/biete-schiffsmodelle.133/"),
    Category("antriebstechnik","Antriebstechnik",           "https://www.rc-network.de/forums/biete-antriebstechnik.134/"),
    Category("rc-elektronik",  "RC-Elektronik & Zubehör",   "https://www.rc-network.de/forums/biete-rc-elektronik-zubeh%C3%B6r.135/"),
    Category("rc-cars",        "RC-Cars & Funktionsmodelle","https://www.rc-network.de/forums/biete-rc-cars-funktionsmodelle.146/"),
    Category("einzelteile",    "Einzelteile & Sonstiges",   "https://www.rc-network.de/forums/biete-einzelteile-sonstiges.136/"),
    Category("verschenken",    "Zu verschenken",            "https://www.rc-network.de/forums/zu-verschenken.11779439/"),
]

CATEGORY_KEYS: set[str] = {c.key for c in CATEGORIES}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = "postgresql+asyncpg://rcscout:rcscout_dev@db:5432/rcscout"
    SCRAPE_DELAY: float = 2.0
    RECHECK_DELAY: float = 2.0
    RECHECK_BATCH_SIZE: int = 250

    # Required — no default (startup fails with clear error if missing)
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    JWT_SECRET: str

    # Optional with sensible defaults
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 30
    PUBLIC_BASE_URL: str = "http://localhost:8002"   # used for OAuth redirect_uri
    FRONTEND_URL: str = "http://localhost:4200"
    ALLOWED_ORIGINS: str = "http://localhost:4200"  # comma-separated
    COOKIE_SECURE: bool = False  # set True in production (HTTPS)

    # OpenRouter — optional, analysis disabled if not set or if LLM_ANALYSIS_ENABLED=false
    LLM_ANALYSIS_ENABLED: bool = True
    OPENROUTER_API_KEY: str = ""
    # Comma-separated list of free-tier models, tried in order on each call.
    # All listed models must support strict structured outputs (response_format=schema).
    # Refresh this list with: python -m app.analysis.list_free_models
    OPENROUTER_FREE_MODELS: str = (
        "qwen/qwen3-next-80b-a3b-instruct:free,"
        "nvidia/nemotron-3-super-120b-a12b:free,"
        "nvidia/nemotron-nano-9b-v2:free,"
        "arcee-ai/trinity-large-preview:free"
    )
    # Paid safety-net, used only when ALL free models in the list failed for a request.
    OPENROUTER_FALLBACK_MODEL: str = "mistralai/mistral-nemo"
    # One-off batch/backfill — paid, unlimited rate.
    OPENROUTER_BATCH_MODEL: str = "google/gemini-2.5-flash-lite"

    @property
    def openrouter_free_models_list(self) -> list[str]:
        """Parse comma-separated OPENROUTER_FREE_MODELS into a list of model IDs."""
        return [m.strip() for m in self.OPENROUTER_FREE_MODELS.split(",") if m.strip()]

    @field_validator("JWT_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse comma-separated ALLOWED_ORIGINS into a list."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()
