"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

# Ensure app-level loggers emit INFO and above.
# basicConfig adds a StreamHandler to the root logger (no-op if already configured).
# The app logger level must also be set — uvicorn only configures its own loggers.
logging.basicConfig(level=logging.WARNING)
logging.getLogger("app").setLevel(logging.INFO)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.api.routes import router
from app.scrape_runner import start_update_job, start_recheck_job

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown logic."""
    from app.db import init_db
    await init_db()
    logger.info("Database initialised")

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
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Scheduler started — update every 30min, recheck every 1h")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(title="RC-Markt Scout", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
