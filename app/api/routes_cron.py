"""Cron endpoints for Vercel scheduled pipeline triggers."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Header

from app.config import get_settings
from app.sheets_db import SheetsDB, get_sheets_db

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_cron_secret(authorization: str = Header(default="")):
    """Verify the cron request comes from Vercel or an authorized source."""
    settings = get_settings()

    if settings.CRON_SECRET:
        expected = f"Bearer {settings.CRON_SECRET}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/run/{project_id}")
def cron_run_pipeline(
    project_id: str,
    db: SheetsDB = Depends(get_sheets_db),
    _auth=Depends(_verify_cron_secret),
):
    """Run the pipeline for a project. Called by Vercel Cron Jobs."""
    project = db.get_project(project_id)
    if not project or not project["is_active"]:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.pipeline.orchestrator import run_pipeline

    try:
        result = run_pipeline(project_id, trigger_type="cron", db=db)
        logger.info(f"Cron pipeline for {project_id} completed: {result['status']}")
        return {
            "status": result["status"],
            "project_id": project_id,
            "articles_fetched": result["articles_fetched"],
            "ai_model_used": result["ai_model_used"],
        }
    except Exception as e:
        logger.error(f"Cron pipeline for {project_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
