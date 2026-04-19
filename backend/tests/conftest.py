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

    # Drop and recreate all tables to ensure schema is always up to date.
    # Manually-created tables (not in Base.metadata) that have FK references to
    # ORM-managed tables must be dropped first, otherwise drop_all fails with
    # DependentObjectsStillExistError when it tries to DROP TABLE users.
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS user_notification_prefs CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS telegram_link_tokens CASCADE"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Apply incremental migrations that are not in ORM models (mirror init_db pattern)
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'member'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"))
        # PLAN-015: user_favorites is already in Base.metadata via UserFavorite model,
        # but the snapshot columns are not in the ORM model — add them here
        await conn.execute(text("ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_is_sold BOOLEAN"))
        await conn.execute(text("ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_price_numeric NUMERIC(10,2)"))
        await conn.execute(text("ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_scraped_at TIMESTAMPTZ"))
        # PLAN-019: Telegram columns on users
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT"))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_chat_id
            ON users (telegram_chat_id) WHERE telegram_chat_id IS NOT NULL
        """))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ"))
        # PLAN-019: telegram_link_tokens table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS telegram_link_tokens (
                token       TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at  TIMESTAMPTZ NOT NULL,
                used_at     TIMESTAMPTZ
            )
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_link_tokens_user ON telegram_link_tokens (user_id)"))
        # PLAN-019: user_notification_prefs table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_notification_prefs (
                user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                new_search_results BOOLEAN NOT NULL DEFAULT TRUE,
                fav_sold           BOOLEAN NOT NULL DEFAULT TRUE,
                fav_price          BOOLEAN NOT NULL DEFAULT TRUE,
                fav_deleted        BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))

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


@pytest.fixture(autouse=True)
def patch_async_session_local(test_engine) -> None:
    """Redirect AsyncSessionLocal to the test engine for the duration of each test.

    Patches both the canonical module (app.db) and every submodule that imported
    it directly (from app.db import AsyncSessionLocal), so that all call-sites
    hit the test DB rather than production.
    """
    import app.db as _db_module  # noqa: PLC0415
    import importlib  # noqa: PLC0415

    test_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Modules that do "from app.db import AsyncSessionLocal" — patch their local ref
    _patch_targets = [
        "app.telegram.bot",
        "app.telegram.link",
        "app.telegram.prefs",
        "app.telegram.plugin",
        "app.telegram.fav_sweep",
    ]

    originals: dict = {"app.db": _db_module.AsyncSessionLocal}
    _db_module.AsyncSessionLocal = test_factory

    for mod_name in _patch_targets:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "AsyncSessionLocal"):
                originals[mod_name] = mod.AsyncSessionLocal
                mod.AsyncSessionLocal = test_factory
        except ImportError:
            pass

    yield

    _db_module.AsyncSessionLocal = originals["app.db"]
    for mod_name in _patch_targets:
        if mod_name in originals:
            mod = importlib.import_module(mod_name)
            mod.AsyncSessionLocal = originals[mod_name]


@pytest_asyncio.fixture(autouse=True)
async def clean_listings(db_session: AsyncSession) -> None:
    """Truncate listings, users and geodata before each test to ensure isolation.

    FK-safe delete order: search_notifications → saved_searches → listings → plz_geodata.
    users is included in the TRUNCATE CASCADE so dependent rows are cleaned up automatically.
    """
    await db_session.execute(text("DELETE FROM search_notifications"))
    await db_session.execute(text("DELETE FROM saved_searches"))
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


# ---------------------------------------------------------------------------
# Telegram test fixtures
# ---------------------------------------------------------------------------

from dataclasses import dataclass  # noqa: E402


@dataclass
class _LinkedUser:
    user_id: int
    chat_id: int


@pytest_asyncio.fixture()
async def db_user(db_session: AsyncSession):
    """Insert a test user (no Telegram link) and return the ORM object."""
    from app.models import User  # noqa: PLC0415

    user = User(
        google_id="test-google-tg",
        email="tg_test@example.com",
        name="TG Test",
        is_approved=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def db_user_linked(db_session: AsyncSession) -> _LinkedUser:
    """Insert a user with telegram_chat_id=12345 and return (user_id, chat_id)."""
    from sqlalchemy import text as _text  # noqa: PLC0415

    await db_session.execute(
        _text("""
            INSERT INTO users (google_id, email, name, is_approved, telegram_chat_id, telegram_linked_at)
            VALUES ('tg-linked-google', 'tg_linked@example.com', 'TG Linked', TRUE, 12345, now())
        """)
    )
    await db_session.commit()
    row = await db_session.execute(
        _text("SELECT id FROM users WHERE google_id = 'tg-linked-google'")
    )
    user_id = row.scalar_one()
    return _LinkedUser(user_id=user_id, chat_id=12345)


@pytest_asyncio.fixture()
async def db_listing(db_session: AsyncSession):
    """Insert a minimal listing and return its id."""
    from sqlalchemy import text as _text  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    await db_session.execute(
        _text("""
            INSERT INTO listings (external_id, url, title, description, author, scraped_at, images, tags)
            VALUES ('tg-test-ext-1', 'http://example.com/1', 'Test Listing TG', 'desc', 'author',
                    :now, '[]', '[]')
        """),
        {"now": now},
    )
    await db_session.commit()
    row = await db_session.execute(
        _text("SELECT id FROM listings WHERE external_id = 'tg-test-ext-1'")
    )
    return type("Listing", (), {"id": row.scalar_one()})()


@pytest_asyncio.fixture()
async def authenticated_client(test_engine, db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient authenticated as a fresh test user (inserted after clean_listings)."""
    from sqlalchemy import text as _text  # noqa: PLC0415
    from app.api.deps import get_current_user  # noqa: PLC0415
    from app.db import get_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    # Insert user in the same db_session that already passed clean_listings
    await db_session.execute(
        _text("""
            INSERT INTO users (google_id, email, name, is_approved)
            VALUES ('auth-client-google', 'auth_client@example.com', 'Auth Client', TRUE)
            ON CONFLICT (google_id) DO NOTHING
        """)
    )
    await db_session.commit()
    row = await db_session.execute(
        _text("SELECT id FROM users WHERE google_id = 'auth-client-google'")
    )
    user_id = row.scalar_one()

    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def _fake_user() -> User:
        async with factory() as session:
            r = await session.execute(
                _text("SELECT id, google_id, email, name, is_approved, role FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            row = r.one()
            return User(id=row[0], google_id=row[1], email=row[2], name=row[3], is_approved=row[4], role=row[5])

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_current_user] = _fake_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def authenticated_client_linked(test_engine, db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient authenticated as a user with telegram_chat_id=99999 (inserted after clean_listings)."""
    from sqlalchemy import text as _text  # noqa: PLC0415
    from app.api.deps import get_current_user  # noqa: PLC0415
    from app.db import get_session  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    await db_session.execute(
        _text("""
            INSERT INTO users (google_id, email, name, is_approved, telegram_chat_id, telegram_linked_at)
            VALUES ('auth-linked-google', 'auth_linked@example.com', 'Auth Linked', TRUE, 99999, now())
            ON CONFLICT (google_id) DO NOTHING
        """)
    )
    await db_session.commit()
    row = await db_session.execute(
        _text("SELECT id FROM users WHERE google_id = 'auth-linked-google'")
    )
    user_id = row.scalar_one()

    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def _fake_user() -> User:
        async with factory() as session:
            r = await session.execute(
                _text("SELECT id, google_id, email, name, is_approved, role FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            row = r.one()
            return User(id=row[0], google_id=row[1], email=row[2], name=row[3], is_approved=row[4], role=row[5])

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_current_user] = _fake_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
