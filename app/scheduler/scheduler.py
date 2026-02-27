"""APScheduler setup for automated pipeline execution."""
import json
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="UTC")


def _parse_cron_entries(schedule_cron) -> list[dict]:
    """Parse schedule_cron into a list of {"cron": str, "platforms": list|None}.

    Supports:
    - Simple cron string: "0 15 * * 1-5"
    - JSON array: [{"cron": "0 15 * * 1,3,5", "platforms": ["linkedin"]}, ...]
    - JSON string of the above
    """
    if not schedule_cron:
        return []

    # Already a list
    if isinstance(schedule_cron, list):
        return schedule_cron

    # Try JSON
    if isinstance(schedule_cron, str) and schedule_cron.strip().startswith("["):
        try:
            parsed = json.loads(schedule_cron)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Plain cron string
    return [{"cron": str(schedule_cron), "platforms": None}]


def init_scheduler():
    """Initialize the scheduler and load project schedules from Sheets."""
    from app.sheets_db import SheetsDB

    db = SheetsDB()
    projects = db.get_active_projects()
    for project in projects:
        add_project_schedule(project["id"], project["schedule_cron"])
    logger.info(f"Scheduler initialized with {len(projects)} project schedules")


def add_project_schedule(project_id: str, cron_expression):
    """Add or update scheduled job(s) for a project.

    Handles both simple cron strings and per-platform schedule arrays.
    """
    entries = _parse_cron_entries(cron_expression)

    # Remove any existing jobs for this project
    for job in scheduler.get_jobs():
        if job.id.startswith(f"pipeline_{project_id}"):
            scheduler.remove_job(job.id)

    for i, entry in enumerate(entries):
        cron_str = entry.get("cron", "") if isinstance(entry, dict) else str(entry)
        platforms = entry.get("platforms") if isinstance(entry, dict) else None
        job_id = f"pipeline_{project_id}_{i}" if len(entries) > 1 else f"pipeline_{project_id}"

        try:
            trigger = CronTrigger.from_crontab(cron_str)
        except Exception as e:
            logger.error(f"Invalid cron expression '{cron_str}' for {project_id}: {e}")
            continue

        plat_label = ",".join(platforms) if platforms else "all"
        scheduler.add_job(
            func=_run_pipeline_job,
            trigger=trigger,
            id=job_id,
            args=[project_id, platforms],
            replace_existing=True,
            misfire_grace_time=300,
            name=f"Pipeline: {project_id} ({plat_label})",
        )
        logger.info(f"Scheduled {project_id} [{plat_label}] with cron: {cron_str}")


def remove_project_schedule(project_id: str):
    """Remove all scheduled jobs for a project."""
    for job in scheduler.get_jobs():
        if job.id.startswith(f"pipeline_{project_id}"):
            scheduler.remove_job(job.id)
            logger.info(f"Removed schedule job {job.id}")


def pause_project_schedule(project_id: str):
    """Pause all of a project's scheduled jobs."""
    for job in scheduler.get_jobs():
        if job.id.startswith(f"pipeline_{project_id}"):
            scheduler.pause_job(job.id)
    logger.info(f"Paused schedule for {project_id}")


def resume_project_schedule(project_id: str):
    """Resume all paused project schedules."""
    for job in scheduler.get_jobs():
        if job.id.startswith(f"pipeline_{project_id}"):
            scheduler.resume_job(job.id)
    logger.info(f"Resumed schedule for {project_id}")


def get_next_run_time(project_id: str):
    """Get the earliest next scheduled run time across all platform schedules."""
    earliest = None
    for job in scheduler.get_jobs():
        if job.id.startswith(f"pipeline_{project_id}") and job.next_run_time:
            if earliest is None or job.next_run_time < earliest:
                earliest = job.next_run_time
    return earliest


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


def _run_pipeline_job(project_id: str, platforms: list[str] = None):
    """Wrapper that creates a SheetsDB and runs the pipeline."""
    try:
        from app.sheets_db import SheetsDB
        from app.pipeline.orchestrator import run_pipeline

        db = SheetsDB()
        result = run_pipeline(project_id, trigger_type="scheduled", db=db, platforms=platforms)
        plat_label = ",".join(platforms) if platforms else "all"
        logger.info(f"Scheduled pipeline for {project_id} [{plat_label}] completed: {result['status']}")
    except Exception as e:
        logger.error(f"Scheduled pipeline for {project_id} failed: {e}")
