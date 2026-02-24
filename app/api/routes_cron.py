"""Cron endpoints for Vercel scheduled pipeline triggers."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Header

from app.config import get_settings
from app.sheets_db import SheetsDB, get_sheets_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_cron_secret(authorization: str = Header(default="")):
    """Verify the cron request comes from Vercel or an authorized source.

    Vercel Cron sends CRON_SECRET as 'Authorization: Bearer <token>'.
    If CRON_SECRET is not configured, auth is skipped (dev mode).
    """
    settings = get_settings()

    if settings.CRON_SECRET:
        expected = f"Bearer {settings.CRON_SECRET}"
        if authorization != expected:
            logger.warning(f"Cron auth failed: got '{authorization[:20]}...'")
            raise HTTPException(status_code=401, detail="Unauthorized")


def _run_project_pipeline(project_id: str, db: SheetsDB, platform_list: list[str] | None = None) -> dict:
    """Shared logic: validate project and execute pipeline."""
    project = db.get_project(project_id)
    if not project or not project["is_active"]:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found or inactive")

    from app.pipeline.orchestrator import run_pipeline

    try:
        result = run_pipeline(project_id, trigger_type="cron", db=db, platforms=platform_list)
        logger.info(f"Cron pipeline for {project_id} completed: {result['status']} (platforms={platform_list})")
        return {
            "status": result["status"],
            "project_id": project_id,
            "articles_fetched": result["articles_fetched"],
            "ai_model_used": result["ai_model_used"],
            "platforms": platform_list or "all",
        }
    except Exception as e:
        logger.error(f"Cron pipeline for {project_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/run/{project_id}/{platforms_path}")
def cron_run_pipeline_with_platforms(
    project_id: str,
    platforms_path: str,
    db: SheetsDB = Depends(get_sheets_db),
    _auth=Depends(_verify_cron_secret),
):
    """Run the pipeline for a project with specific platforms (path-based).

    Used by Vercel Cron which does not support query strings in paths.
    The platforms_path is a comma-separated list, e.g. 'linkedin' or 'linkedin,twitter'.
    """
    platform_list = [p.strip() for p in platforms_path.split(",") if p.strip()]
    return _run_project_pipeline(project_id, db, platform_list)


@router.get("/run/{project_id}")
def cron_run_pipeline(
    project_id: str,
    platforms: str = None,
    db: SheetsDB = Depends(get_sheets_db),
    _auth=Depends(_verify_cron_secret),
):
    """Run the pipeline for a project. Called by Vercel Cron Jobs.

    Args:
        platforms: Comma-separated platforms to publish to (e.g. "linkedin,twitter").
                   If not set, publishes to all configured platforms.
    """
    platform_list = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None
    return _run_project_pipeline(project_id, db, platform_list)


@router.get("/run-all")
def cron_run_all(
    db: SheetsDB = Depends(get_sheets_db),
    _auth=Depends(_verify_cron_secret),
):
    """Run the pipeline for all active projects."""
    projects = db.get_active_projects()
    results = []

    for project in projects:
        try:
            from app.pipeline.orchestrator import run_pipeline
            result = run_pipeline(project["id"], trigger_type="cron", db=db)
            results.append({"project_id": project["id"], "status": result["status"]})
            logger.info(f"Cron pipeline for {project['id']} completed: {result['status']}")
        except Exception as e:
            results.append({"project_id": project["id"], "status": "error", "error": str(e)})
            logger.error(f"Cron pipeline for {project['id']} failed: {e}")

    return {"results": results}
