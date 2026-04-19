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
        # LLM free-tier cascade — dynamic, refreshed every 12h from OpenRouter API.
        # See app/analysis/model_cascade.py for read/write logic.
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS llm_models (
                model_id              TEXT PRIMARY KEY,
                position              INTEGER NOT NULL,
                context_length        INTEGER,
                created_upstream      TIMESTAMPTZ,
                added_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_refresh_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                consecutive_failures  INTEGER NOT NULL DEFAULT 0,
                disabled_until        TIMESTAMPTZ,
                last_error            TEXT
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_llm_models_position ON llm_models (position)"
        ))
        # is_active column added after initial draft (PLAN-018 reviewer fix)
        await conn.execute(text(
            "ALTER TABLE llm_models ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
        ))
        # PLAN-019: Telegram notifications
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT"
        ))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_users_telegram_chat_id
            ON users (telegram_chat_id) WHERE telegram_chat_id IS NOT NULL
        """))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS telegram_link_tokens (
                token       TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at  TIMESTAMPTZ NOT NULL,
                used_at     TIMESTAMPTZ
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_telegram_link_tokens_user ON telegram_link_tokens (user_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_notification_prefs (
                user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                new_search_results BOOLEAN NOT NULL DEFAULT TRUE,
                fav_sold           BOOLEAN NOT NULL DEFAULT TRUE,
                fav_price          BOOLEAN NOT NULL DEFAULT TRUE,
                fav_deleted        BOOLEAN NOT NULL DEFAULT TRUE,
                fav_indicator      BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_is_sold BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_price_numeric NUMERIC(10,2)"
        ))
        await conn.execute(text(
            "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_price_indicator VARCHAR(20)"
        ))
        await conn.execute(text(
            "ALTER TABLE user_favorites ADD COLUMN IF NOT EXISTS last_known_scraped_at TIMESTAMPTZ"
        ))
        # PLAN-023: eBay second source
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'rcnetwork'"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_listings_source ON listings (source)"
        ))
        # PLAN-007: lifecycle timestamps
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ))
        # One-time backfill: only runs when created_at was just added (default = now() would be wrong
        # for existing rows). Guard: only update rows where created_at is newer than scraped_at,
        # which can only happen for rows that just received the column default.
        # Note: all statements run in a single transaction (engine.begin()) — now() is constant
        # per transaction, so rows inserted during this same transaction have created_at == scraped_at
        # and will not match the guard.
        await conn.execute(text(
            "UPDATE listings SET created_at = scraped_at WHERE created_at > scraped_at"
        ))
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS sold_at TIMESTAMPTZ"
        ))
        # PLAN-024: soft outdated flag
        await conn.execute(text(
            "ALTER TABLE listings ADD COLUMN IF NOT EXISTS is_outdated BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        # Backfill: mark existing rows whose posted_at is older than 8 weeks and are not sold.
        # Guard AND is_outdated = FALSE makes this idempotent — rows already marked are skipped.
        # All statements run inside engine.begin() (single transaction), so now() is constant.
        await conn.execute(text(
            """
            UPDATE listings
            SET is_outdated = TRUE
            WHERE is_sold = FALSE
              AND posted_at IS NOT NULL
              AND posted_at < NOW() - INTERVAL '8 weeks'
              AND is_outdated = FALSE
            """
        ))
        # PLAN-025: remove median-based price indicator system
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS price_indicator"
        ))
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS price_indicator_median"
        ))
        await conn.execute(text(
            "ALTER TABLE listings DROP COLUMN IF EXISTS price_indicator_count"
        ))
        await conn.execute(text(
            "ALTER TABLE user_favorites DROP COLUMN IF EXISTS last_known_price_indicator"
        ))
        # Telegram notification preference for price indicator changes — also gone.
        await conn.execute(text(
            "ALTER TABLE user_notification_prefs DROP COLUMN IF EXISTS fav_indicator"
        ))


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
