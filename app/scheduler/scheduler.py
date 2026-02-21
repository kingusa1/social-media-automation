"""APScheduler setup for automated pipeline execution."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def init_scheduler():
    """Initialize the scheduler and load project schedules from Sheets."""
    from app.sheets_db import SheetsDB

    db = SheetsDB()
    projects = db.get_active_projects()
    for project in projects:
        add_project_schedule(project["id"], project["schedule_cron"])
    logger.info(f"Scheduler initialized with {len(projects)} project schedules")


def add_project_schedule(project_id: str, cron_expression: str):
    """Add or update a scheduled job for a project."""
    job_id = f"pipeline_{project_id}"

    try:
        trigger = CronTrigger.from_crontab(cron_expression)
    except Exception as e:
        logger.error(f"Invalid cron expression '{cron_expression}' for {project_id}: {e}")
        return

    existing = scheduler.get_job(job_id)
    if existing:
        scheduler.remove_job(job_id)

    scheduler.add_job(
        func=_run_pipeline_job,
        trigger=trigger,
        id=job_id,
        args=[project_id],
        replace_existing=True,
        misfire_grace_time=300,
        name=f"Pipeline: {project_id}",
    )
    logger.info(f"Scheduled pipeline for {project_id} with cron: {cron_expression}")


def remove_project_schedule(project_id: str):
    """Remove a scheduled job."""
    job_id = f"pipeline_{project_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Removed schedule for {project_id}")


def pause_project_schedule(project_id: str):
    """Pause a project's scheduled job."""
    job_id = f"pipeline_{project_id}"
    if scheduler.get_job(job_id):
        scheduler.pause_job(job_id)
        logger.info(f"Paused schedule for {project_id}")


def resume_project_schedule(project_id: str):
    """Resume a paused project schedule."""
    job_id = f"pipeline_{project_id}"
    if scheduler.get_job(job_id):
        scheduler.resume_job(job_id)
        logger.info(f"Resumed schedule for {project_id}")


def get_next_run_time(project_id: str):
    """Get the next scheduled run time for a project."""
    job_id = f"pipeline_{project_id}"
    job = scheduler.get_job(job_id)
    if job:
        return job.next_run_time
    return None


def get_all_jobs() -> list[dict]:
    """List all scheduled jobs with their status and next run times."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "is_paused": job.next_run_time is None,
        })
    return jobs


def start():
    """Start the scheduler."""
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def shutdown():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def _run_pipeline_job(project_id: str):
    """Wrapper that creates a SheetsDB and runs the pipeline."""
    try:
        from app.sheets_db import SheetsDB
        from app.pipeline.orchestrator import run_pipeline

        db = SheetsDB()
        result = run_pipeline(project_id, trigger_type="scheduled", db=db)
        logger.info(f"Scheduled pipeline for {project_id} completed: {result['status']}")
    except Exception as e:
        logger.error(f"Scheduled pipeline for {project_id} failed: {e}")
