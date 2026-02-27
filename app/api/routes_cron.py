"""Cron endpoints for Vercel scheduled pipeline triggers.

Uses a single hourly cron that checks each project's schedule_cron from
Google Sheets. Supports per-platform scheduling:
  - Simple cron: "0 14 * * *" → runs all platforms
  - JSON array: [{"cron": "0 15 * * 1,3,5", "platforms": ["linkedin"]}, ...] → per-platform
"""
import json
import logging
from datetime import datetime, timezone, timedelta
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


def _parse_schedules(project: dict) -> list[dict]:
    """Parse schedule_cron into a list of schedule entries.

    Supports two formats:
    1. Simple cron string: "0 15 * * 1-5" → all platforms
    2. JSON array: [{"cron": "0 15 * * 1,3,5", "platforms": ["linkedin"]}, ...]
    """
    raw = project.get("schedule_cron", "")
    if not raw:
        return []

    # Already a list (e.g. from _parse_json in sheets_db)
    if isinstance(raw, list):
        return raw

    # Try JSON array format
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Simple cron string - applies to all platforms
    return [{"cron": str(raw), "platforms": None}]


def _cron_matches_now(cron_expr: str, now: datetime) -> bool:
    """Check if a cron expression matches the current UTC hour and day.

    Only supports: minute hour * * day_of_week
    Returns True if current hour matches AND current day_of_week matches.
    We ignore minutes since the cron fires at the top of each hour.
    """
    try:
        parts = cron_expr.strip().split()
        if len(parts) < 5:
            return False

        cron_hour = int(parts[1])
        dow_spec = parts[4]  # day of week: * or 0-6 or 1-5 or 1,3,5

        # Check hour
        if now.hour != cron_hour:
            return False

        # Check day of week (0=Sun in cron, but Python weekday() 0=Mon..6=Sun)
        if dow_spec != "*":
            py_dow = now.weekday()  # 0=Mon..6=Sun
            # Convert to cron format: 0=Sun,1=Mon..6=Sat
            cron_dow = (py_dow + 1) % 7

            # Parse allowed days: "1-5" or "0,2,4,6" or "1,3,5"
            allowed = set()
            for part in dow_spec.split(","):
                if "-" in part:
                    lo, hi = part.split("-", 1)
                    allowed.update(range(int(lo), int(hi) + 1))
                else:
                    allowed.add(int(part))

            if cron_dow not in allowed:
                return False

        return True
    except Exception as e:
        logger.error(f"Failed to parse cron '{cron_expr}': {e}")
        return False


def _ran_recently(db: SheetsDB, project_id: str, hours: float = 1.5) -> bool:
    """Check if the project ran within the last N hours to prevent duplicates."""
    runs = db.get_pipeline_runs(project_id=project_id, limit=1)
    if not runs:
        return False

    last_run = runs[0]
    started_at = last_run.get("started_at")
    if not started_at:
        return False

    if isinstance(started_at, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                started_at = datetime.strptime(started_at, fmt)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            return False

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return started_at > cutoff


@router.get("/check")
def cron_check_all(
    db: SheetsDB = Depends(get_sheets_db),
    _auth=Depends(_verify_cron_secret),
):
    """Smart scheduler: runs every hour, checks which projects are due.

    Reads each project's schedule_cron from Google Sheets and runs the
    pipeline only if the current UTC hour/day matches. Supports per-platform
    scheduling (different crons for LinkedIn vs Twitter).

    For per-platform schedules, all platforms due at the same hour are
    combined into a single pipeline run for efficiency.
    """
    now = datetime.now(timezone.utc)
    projects = db.get_active_projects()
    results = []

    logger.info(f"Cron check at {now.strftime('%Y-%m-%d %H:%M UTC')} - "
                f"checking {len(projects)} active projects")

    for project in projects:
        pid = project["id"]
        schedules = _parse_schedules(project)

        if not schedules:
            logger.warning(f"Project {pid} has no schedule, skipping")
            results.append({"project_id": pid, "status": "skipped", "reason": "no schedule"})
            continue

        # Collect all platforms due at this hour
        platforms_due = set()
        all_platforms = False
        matched_crons = []

        for sched in schedules:
            cron_expr = sched.get("cron", "")
            if _cron_matches_now(cron_expr, now):
                plats = sched.get("platforms")
                if plats is None:
                    # No platform filter = all platforms
                    all_platforms = True
                    matched_crons.append(cron_expr)
                    break
                else:
                    platforms_due.update(plats)
                    matched_crons.append(f"{cron_expr} ({','.join(plats)})")

        if not all_platforms and not platforms_due:
            results.append({"project_id": pid, "status": "skipped",
                           "reason": "not scheduled now"})
            continue

        # Check for recent runs to prevent duplicates
        if _ran_recently(db, pid, hours=1.5):
            logger.info(f"Project {pid} already ran recently, skipping")
            results.append({"project_id": pid, "status": "skipped", "reason": "ran recently"})
            continue

        platform_list = None if all_platforms else list(platforms_due)

        logger.info(f"Project {pid} is due (matched: {matched_crons}), "
                    f"platforms: {platform_list or 'all'}")

        try:
            from app.pipeline.orchestrator import run_pipeline
            result = run_pipeline(pid, trigger_type="cron", db=db, platforms=platform_list)
            results.append({
                "project_id": pid,
                "status": result["status"],
                "platforms": platform_list or "all",
            })
            logger.info(f"Pipeline for {pid} completed: {result['status']} "
                       f"(platforms: {platform_list or 'all'})")
        except Exception as e:
            results.append({"project_id": pid, "status": "error", "error": str(e)})
            logger.error(f"Pipeline for {pid} failed: {e}")

    return {"checked_at": now.isoformat(), "results": results}


@router.get("/run/{project_id}")
def cron_run_pipeline(
    project_id: str,
    platforms: str = None,
    db: SheetsDB = Depends(get_sheets_db),
    _auth=Depends(_verify_cron_secret),
):
    """Run the pipeline for a specific project (manual trigger or direct cron)."""
    project = db.get_project(project_id)
    if not project or not project["is_active"]:
        raise HTTPException(status_code=404, detail="Project not found")

    platform_list = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None

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
