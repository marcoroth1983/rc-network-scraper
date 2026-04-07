"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

# Ensure app-level loggers emit INFO and above (uvicorn only configures its own loggers)
logging.getLogger("app").setLevel(logging.INFO)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.api.routes import router
from app.scrape_runner import start_background_job

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup and shutdown logic."""
    from app.db import init_db
    await init_db()
    logger.info("Database initialised")

    # Create a fresh scheduler per lifespan cycle — avoids stale state on hot-reload.
    # The job calls start_background_job (sync) which creates a GC-safe asyncio.Task.
    # First auto-scrape fires 4 hours after process start (not immediately on boot).
    # To trigger an immediate scrape, use the manual button in the UI.
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        start_background_job,
        trigger="interval",
        hours=4,
        id="auto_scrape",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Scheduler started — auto-scrape every 4 hours (first run in 4h)")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(title="RC-Markt Scout", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
