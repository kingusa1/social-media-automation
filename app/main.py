"""FastAPI application setup with lifespan management."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    from app.sheets_db import init_sheets

    # Startup
    logger.info("Starting Social Media Automation System...")
    init_sheets()

    # Only use APScheduler when running locally (not on Vercel serverless)
    if not settings.is_vercel:
        from app.scheduler.scheduler import init_scheduler, start as start_scheduler, shutdown as shutdown_scheduler
        init_scheduler()
        start_scheduler()
    else:
        logger.info("Running on Vercel - using cron jobs instead of APScheduler")

    logger.info("System ready!")
    yield

    # Shutdown
    if not settings.is_vercel:
        from app.scheduler.scheduler import shutdown as shutdown_scheduler
        shutdown_scheduler()
    logger.info("System shut down.")


app = FastAPI(
    title="Social Media Automation",
    description="Operations dashboard for Infiniteo & YourOps content automation",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# Import and include routers
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_api import router as api_router
from app.api.routes_auth import router as auth_router
from app.api.routes_cron import router as cron_router

app.include_router(dashboard_router)
app.include_router(api_router, prefix="/api")
app.include_router(auth_router, prefix="/auth")
app.include_router(cron_router, prefix="/api/cron")
