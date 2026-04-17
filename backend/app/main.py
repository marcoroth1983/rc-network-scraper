"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx

# Ensure app-level loggers emit INFO and above.
# basicConfig adds a StreamHandler to the root logger (no-op if already configured).
# The app logger level must also be set — uvicorn only configures its own loggers.
logging.basicConfig(level=logging.WARNING)
logging.getLogger("app").setLevel(logging.INFO)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.routes import router
from app.telegram.webhook import router as telegram_webhook_router
from app.config import settings
from app.notifications.log_plugin import LogPlugin
from app.notifications.registry import notification_registry
from app.telegram.plugin import TelegramPlugin
from app.analysis.job import run_analysis_job
from app.analysis import model_cascade
from app.scrape_runner import start_update_job, start_recheck_job

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown logic."""
    from app.db import init_db
    await init_db()
    logger.info("Database initialised")

    # Seed LLM cascade table from env if empty (first boot / fresh DB)
    try:
        await model_cascade.seed_if_empty()
    except Exception as exc:
        logger.warning("model_cascade seed failed: %s", exc)

    # Register notification plugins — guard against hot-reload duplicates
    if not notification_registry._plugins:
        notification_registry.register(LogPlugin())

    if settings.telegram_enabled and not any(
        isinstance(p, TelegramPlugin) for p in notification_registry._plugins
    ):
        notification_registry.register(TelegramPlugin())
        logger.info("telegram.plugin: registered in notification_registry")

    # Create a fresh scheduler per lifespan cycle — avoids stale state on hot-reload.
    # update job: crawl overview pages every 30 minutes (Phase 1 only).
    # recheck job: sold-recheck + cleanup every 1 hour (Phase 2+3).
    # Neither job fires immediately on startup — first run after the interval elapses.
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        start_update_job,
        trigger="interval",
        minutes=30,
        id="auto_update",
        replace_existing=True,
    )
    scheduler.add_job(
        start_recheck_job,
        trigger="interval",
        hours=1,
        id="auto_recheck",
        replace_existing=True,
    )
    scheduler.add_job(
        run_analysis_job,
        trigger="interval",
        minutes=2,
        id="auto_analysis",
        replace_existing=True,
    )
    scheduler.add_job(
        model_cascade.refresh_job,
        trigger="interval",
        hours=settings.LLM_CASCADE_REFRESH_HOURS,
        id="llm_cascade_refresh",
        next_run_time=datetime.now(timezone.utc),  # run once on boot with live data
        replace_existing=True,
    )
    if settings.telegram_enabled:
        from app.telegram import fav_sweep  # local import — only when telegram is active
        scheduler.add_job(
            fav_sweep.run_fav_status_sweep,
            trigger="interval",
            minutes=settings.TELEGRAM_FAV_SWEEP_INTERVAL_MIN,
            id="telegram_fav_status_sweep",
            replace_existing=True,
        )

    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Scheduler started — update every 30min, recheck every 1h, "
        "analysis every 2min, llm_cascade_refresh every %gh",
        settings.LLM_CASCADE_REFRESH_HOURS,
    )

    if settings.telegram_enabled:
        webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/telegram/webhook"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook",
                    json={
                        "url": webhook_url,
                        "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
                        "allowed_updates": ["message"],
                    },
                )
            if r.status_code == 200 and r.json().get("ok"):
                logger.info("telegram: bot configured, webhook registered at %s", webhook_url)
            else:
                logger.warning(
                    "telegram: setWebhook returned %d %s", r.status_code, r.text[:200]
                )
        except httpx.HTTPError as exc:
            logger.warning("telegram: setWebhook failed: %s", exc)
    else:
        logger.info(
            "telegram: disabled (missing TELEGRAM_BOT_TOKEN or username or webhook_secret)"
        )

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(title="RC-Markt Scout", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(router)  # existing business router — unchanged
app.include_router(telegram_webhook_router)  # absolute prefix /api/telegram


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
