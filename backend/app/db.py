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
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'member'"
        ))
        await conn.execute(text(
            "UPDATE users SET role = 'admin' WHERE email = 'marco.roth1983@googlemail.com' AND role = 'member'"
        ))
        # PLAN-014: LLM analysis fields
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS manufacturer VARCHAR(100)"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS model_name VARCHAR(200)"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS drive_type VARCHAR(30)"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS model_type VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS model_subtype VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS completeness VARCHAR(30)"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS attributes JSONB NOT NULL DEFAULT '{}'"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS llm_analyzed BOOLEAN NOT NULL DEFAULT false"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS price_indicator VARCHAR(20)"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS shipping_available BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS analyzed_at"
        ))
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS analysis_retries"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS price_indicator_median NUMERIC"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS price_indicator_count INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"
        ))
        # PLAN-015: user-specific favorites
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_favorites (
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (user_id, listing_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_user_favorites_user_id ON user_favorites (user_id)"
        ))
        # Migrate existing favorites to the admin user (only if legacy column still exists)
        await conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'listings' AND column_name = 'is_favorite'
                ) THEN
                    INSERT INTO user_favorites (user_id, listing_id, created_at)
                    SELECT u.id, l.id, COALESCE(l.favorited_at, now())
                    FROM listings l
                    JOIN users u ON u.email = 'marco.roth1983@googlemail.com'
                    WHERE l.is_favorite = TRUE
                    ON CONFLICT (user_id, listing_id) DO NOTHING;
                END IF;
            END
            $$
        """))
        # Drop legacy columns (data already migrated above)
        await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS is_favorite"))
        await conn.execute(text("ALTER TABLE listings DROP COLUMN IF EXISTS favorited_at"))


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
