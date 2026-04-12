"""Shared pytest fixtures: DB session, HTML fixture helpers."""

import os

# Set required OAuth/JWT env vars before any app imports so Settings validation passes.
# Use direct assignment (not setdefault) because docker-compose may set these as
# empty strings, which setdefault would not override.
os.environ["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID") or "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET") or "test-client-secret"
os.environ["JWT_SECRET"] = os.environ.get("JWT_SECRET") or "test-jwt-secret-for-testing-only"

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://rcscout:rcscout_dev@db:5432/rcscout_test",
)


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Return the database URL used for tests."""
    return _TEST_DB_URL


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_db_url: str):
    """Create a single async engine for the entire test session."""
    from app.models import Base  # noqa: PLC0415

    engine = create_async_engine(test_db_url, echo=False)

    # Drop and recreate all tables to ensure schema is always up to date
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session bound to the test engine.

    Isolation is handled by the ``clean_listings`` autouse fixture in
    test_orchestration.py, which truncates listings before each test.
    This keeps the implementation simple and avoids conflicts with the
    orchestrator's own ``session.commit()`` calls.
    """
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def clean_listings(db_session: AsyncSession) -> None:
    """Truncate listings, users and plz_geodata before each test to ensure isolation."""
    await db_session.execute(text("TRUNCATE TABLE listings, users RESTART IDENTITY CASCADE"))
    await db_session.execute(text("DELETE FROM plz_geodata"))
    await db_session.commit()


@pytest_asyncio.fixture()
async def api_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient wired to the test DB via dependency_overrides."""
    from app.api.deps import get_current_user  # noqa: PLC0415
    from app.db import get_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    def _fake_user() -> User:
        return User(
            id=1,
            google_id="test-google-id",
            email="test@example.com",
            name="Test User",
            is_approved=True,
        )

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_current_user] = _fake_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# HTML fixture helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load an HTML fixture file by filename (e.g. 'overview_page.html')."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_scrape_runner():
    """Reset scrape_runner module state before each test."""
    from app.scrape_runner import reset_state
    reset_state()
    yield
    reset_state()
