"""Cron endpoints for Vercel scheduled pipeline triggers."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Project

router = APIRouter()
logger = logging.getLogger(__name__)


def _verify_cron_secret(authorization: str = Header(default="")):
    """Verify the cron request comes from Vercel or an authorized source."""
    settings = get_settings()

    # Vercel sends cron secret as "Bearer <secret>" in Authorization header
    if settings.CRON_SECRET:
        expected = f"Bearer {settings.CRON_SECRET}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/run/{project_id}")
def cron_run_pipeline(
    project_id: str,
    db: Session = Depends(get_db),
    _auth=Depends(_verify_cron_secret),
):
    """Run the pipeline for a project. Called by Vercel Cron Jobs.

    This runs synchronously since Vercel cron jobs wait for the response.
    """
    project = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.pipeline.orchestrator import run_pipeline

    try:
        result = run_pipeline(project_id, trigger_type="cron", db=db)
        logger.info(f"Cron pipeline for {project_id} completed: {result.status}")
        return {
            "status": result.status,
            "project_id": project_id,
            "articles_fetched": result.articles_fetched,
            "ai_model_used": result.ai_model_used,
        }
    except Exception as e:
        logger.error(f"Cron pipeline for {project_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/run-all")
def cron_run_all(
    db: Session = Depends(get_db),
    _auth=Depends(_verify_cron_secret),
):
    """Run the pipeline for all active projects."""
    projects = db.query(Project).filter(Project.is_active == True).all()
    results = []

    for project in projects:
        try:
            from app.pipeline.orchestrator import run_pipeline
            result = run_pipeline(project.id, trigger_type="cron", db=db)
            results.append({"project_id": project.id, "status": result.status})
            logger.info(f"Cron pipeline for {project.id} completed: {result.status}")
        except Exception as e:
            results.append({"project_id": project.id, "status": "error", "error": str(e)})
            logger.error(f"Cron pipeline for {project.id} failed: {e}")

    return {"results": results}
