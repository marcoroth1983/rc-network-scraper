"""SQLAlchemy async engine, session factory, and init_db helper."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create all tables and apply incremental column additions."""
    from app.models import Base  # local import avoids circular dependency at module load
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Incremental additions — idempotent, safe to run on every startup
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_sold BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS price_numeric NUMERIC(10,2)"
        ))
        # price_numeric is populated on each upsert via _parse_price_numeric() in orchestrator.py.
        # Existing rows will receive the correct value on their next scrape cycle.
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS category VARCHAR(50) NOT NULL DEFAULT 'flugmodelle'"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_listings_category ON listings (category)"
        ))
        await conn.execute(text(
            "ALTER TABLE saved_searches ADD COLUMN IF NOT EXISTS category VARCHAR(50)"
        ))


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
