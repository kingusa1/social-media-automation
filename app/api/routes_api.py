"""REST API endpoints for the dashboard (JSON responses)."""
import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.sheets_db import SheetsDB, get_sheets_db

logger = logging.getLogger(__name__)
from app.schemas import (
    ProjectUpdate, ProfileUpdate, ManualTriggerRequest,
)
from app.scheduler.scheduler import (
    get_all_jobs, add_project_schedule,
    pause_project_schedule, resume_project_schedule,
)


def _next_cron_time(cron_expr: str, now: datetime) -> datetime | None:
    """Compute the next UTC datetime a cron expression will fire."""
    try:
        parts = cron_expr.strip().split()
        if len(parts) < 5:
            return None
        minute = int(parts[0])
        hour = int(parts[1])
        dow_spec = parts[4]

        allowed_days = None
        if dow_spec != "*":
            allowed_days = set()
            for chunk in dow_spec.split(","):
                if "-" in chunk:
                    lo, hi = chunk.split("-", 1)
                    allowed_days.update(range(int(lo), int(hi) + 1))
                else:
                    allowed_days.add(int(chunk))

        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=timezone.utc)
        if candidate <= now:
            candidate += timedelta(days=1)

        if allowed_days is not None:
            for _ in range(8):
                cron_dow = (candidate.weekday() + 1) % 7  # Python Mon=0 -> cron Mon=1
                if cron_dow in allowed_days:
                    break
                candidate += timedelta(days=1)

        return candidate
    except Exception:
        return None


def _compute_next_run(schedule_cron) -> datetime | None:
    """Compute the earliest next run from a schedule_cron (string or array)."""
    now = datetime.now(timezone.utc)

    if isinstance(schedule_cron, list):
        entries = schedule_cron
    elif isinstance(schedule_cron, str):
        if schedule_cron.strip().startswith("["):
            try:
                entries = json.loads(schedule_cron)
            except (json.JSONDecodeError, ValueError):
                entries = [{"cron": schedule_cron}]
        else:
            entries = [{"cron": schedule_cron}]
    else:
        return None

    earliest = None
    for entry in entries:
        cron_expr = entry.get("cron", "") if isinstance(entry, dict) else str(entry)
        nxt = _next_cron_time(cron_expr, now)
        if nxt and (earliest is None or nxt < earliest):
            earliest = nxt

    return earliest

router = APIRouter()


# ========== Dashboard Overview ==========

@router.get("/overview")
def get_overview(db: SheetsDB = Depends(get_sheets_db)):
    """Get dashboard overview for all projects with connection status."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.cleanup_stuck_runs(cutoff)
    except Exception as e:
        logger.warning(f"Cleanup stuck runs failed: {e}")

    projects = db.get_all_projects()
    all_runs = db.get_pipeline_runs()
    all_posts = db.get_generated_posts()
    all_articles = db.get_articles()
    all_profiles = db.get_all_profiles()

    project_data = []
    for p in projects:
        pid = p["id"]
        p_runs = [r for r in all_runs if r["project_id"] == pid]
        last_run = p_runs[0] if p_runs else None

        next_run = _compute_next_run(p["schedule_cron"])

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        p_posts = [pp for pp in all_posts if pp["project_id"] == pid]
        today_posts = sum(1 for pp in p_posts if pp.get("created_at") and pp["created_at"] >= today_start.isoformat())
        total_posts = len(p_posts)

        p_articles = [a for a in all_articles if a["project_id"] == pid]
        total_articles = len(p_articles)
        total_runs = len(p_runs)
        success_runs = sum(1 for r in p_runs if r["status"] == "success")

        p_profiles = [pr for pr in all_profiles if pr["project_id"] == pid]
        linkedin_connected = any(pr["platform"] == "linkedin" and pr["access_token"] for pr in p_profiles)
        twitter_connected = any(pr["platform"] == "twitter" and pr["access_token"] for pr in p_profiles)

        project_data.append({
            "id": pid,
            "display_name": p["display_name"],
            "is_active": p["is_active"],
            "twitter_enabled": p["twitter_enabled"],
            "linkedin_connected": linkedin_connected,
            "twitter_connected": twitter_connected,
            "last_run": {
                "status": last_run["status"] if last_run else "never",
                "time": last_run["started_at"] if last_run else None,
                "used_fallback": last_run["used_fallback"] if last_run else False,
            } if last_run else None,
            "next_run": next_run.isoformat() if next_run else None,
            "schedule_cron": p["schedule_cron"],
            "today_posts": today_posts,
            "total_posts": total_posts,
            "total_articles": total_articles,
            "total_runs": total_runs,
            "success_runs": success_runs,
        })

    recent_runs = all_runs[:10]

    return {
        "projects": project_data,
        "recent_runs": [
            {
                "id": r["id"],
                "project_id": r["project_id"],
                "status": r["status"],
                "trigger_type": r["trigger_type"],
                "started_at": r["started_at"],
                "used_fallback": r["used_fallback"],
            }
            for r in recent_runs
        ],
    }


# ========== Health / Diagnostics ==========

@router.get("/health")
def health_check():
    """Diagnostic endpoint to verify AI config is loaded."""
    settings = get_settings()
    return {
        "api_base": settings.POLLINATIONS_API_BASE,
        "primary_model": settings.POLLINATIONS_PRIMARY_MODEL,
        "fallback_models": settings.fallback_models,
        "api_key_set": bool(settings.POLLINATIONS_API_KEY),
        "api_key_prefix": settings.POLLINATIONS_API_KEY[:8] + "..." if settings.POLLINATIONS_API_KEY else "NOT SET",
        "is_vercel": settings.is_vercel,
    }


# ========== Pipeline Runs ==========

@router.get("/runs")
def list_runs(
    project_id: str = None,
    page: int = 1,
    per_page: int = 20,
    db: SheetsDB = Depends(get_sheets_db),
):
    """List pipeline runs with pagination."""
    runs = db.get_pipeline_runs(project_id=project_id)

    total = len(runs)
    start = (page - 1) * per_page
    page_runs = runs[start:start + per_page]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "runs": [
            {
                "id": r["id"],
                "project_id": r["project_id"],
                "trigger_type": r["trigger_type"],
                "status": r["status"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"] or None,
                "articles_fetched": r["articles_fetched"],
                "articles_new": r["articles_new"],
                "ai_model_used": r["ai_model_used"],
                "used_fallback": r["used_fallback"],
                "error_message": r["error_message"],
                "selected_article_title": _get_article_title(db, r.get("selected_article_id")),
            }
            for r in page_runs
        ],
    }


@router.get("/runs/{run_id}")
def get_run_detail(run_id: int, db: SheetsDB = Depends(get_sheets_db)):
    """Get detailed info for a single pipeline run."""
    run = db.get_pipeline_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    posts = db.get_generated_posts(pipeline_run_id=run_id)
    selected_article = db.get_article(run["selected_article_id"]) if run.get("selected_article_id") else None

    return {
        "id": run["id"],
        "project_id": run["project_id"],
        "trigger_type": run["trigger_type"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"] or None,
        "articles_fetched": run["articles_fetched"],
        "articles_new": run["articles_new"],
        "ai_model_used": run["ai_model_used"],
        "used_fallback": run["used_fallback"],
        "error_message": run["error_message"],
        "log_details": run["log_details"] if isinstance(run["log_details"], list) else [],
        "selected_article": {
            "title": selected_article["title"],
            "url": selected_article["url"],
            "score": selected_article["relevance_score"],
        } if selected_article else None,
        "posts": [
            {
                "id": p["id"],
                "platform": p["platform"],
                "content": p["content"],
                "is_fallback": p["is_fallback"],
                "quality_score": p["quality_score"],
                "publish_results": db.get_publish_results(generated_post_id=p["id"]),
            }
            for p in posts
        ],
    }


@router.post("/runs/trigger")
def trigger_pipeline(request: ManualTriggerRequest, db: SheetsDB = Depends(get_sheets_db)):
    """Manually trigger a pipeline run for a project."""
    project = db.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    running = db.get_running_pipeline(request.project_id)
    if running:
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")

    settings = get_settings()

    if settings.is_vercel:
        from app.pipeline.orchestrator import run_pipeline
        try:
            result = run_pipeline(request.project_id, trigger_type="manual", db=db)
            return {
                "message": f"Pipeline completed for {project['display_name']}",
                "project_id": request.project_id,
                "status": result["status"] if result else "unknown",
                "articles_fetched": result["articles_fetched"] if result else 0,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        def _run():
            try:
                sheets_db = SheetsDB()
                from app.pipeline.orchestrator import run_pipeline
                result = run_pipeline(request.project_id, trigger_type="manual", db=sheets_db)
                logger.info(f"Manual pipeline for {request.project_id} completed: {result['status']}")
            except Exception as e:
                logger.error(f"Manual pipeline for {request.project_id} failed: {e}", exc_info=True)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {"message": f"Pipeline triggered for {project['display_name']}", "project_id": request.project_id}


# ========== Generated Posts ==========

@router.get("/posts")
def list_posts(
    project_id: str = None,
    page: int = 1,
    per_page: int = 20,
    db: SheetsDB = Depends(get_sheets_db),
):
    """List generated posts with pagination."""
    posts = db.get_generated_posts(project_id=project_id)

    total = len(posts)
    start = (page - 1) * per_page
    page_posts = posts[start:start + per_page]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "posts": [
            {
                "id": p["id"],
                "pipeline_run_id": p["pipeline_run_id"],
                "project_id": p["project_id"],
                "platform": p["platform"],
                "content": p["content"],
                "article_url": p["article_url"],
                "article_title": p["article_title"],
                "is_fallback": p["is_fallback"],
                "quality_score": p["quality_score"],
                "created_at": p["created_at"],
                "publish_results": [
                    {
                        "account_type": pr["account_type"],
                        "status": pr["status"],
                        "error_message": pr["error_message"],
                    }
                    for pr in db.get_publish_results(generated_post_id=p["id"])
                ],
            }
            for p in page_posts
        ],
    }


# ========== Articles ==========

@router.get("/articles")
def list_articles(
    project_id: str = None,
    page: int = 1,
    per_page: int = 50,
    db: SheetsDB = Depends(get_sheets_db),
):
    """List articles with scores."""
    articles = db.get_articles(project_id=project_id)

    total = len(articles)
    start = (page - 1) * per_page
    page_articles = articles[start:start + per_page]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "articles": [
            {
                "id": a["id"],
                "project_id": a["project_id"],
                "url": a["url"],
                "title": a["title"],
                "source_feed": a["source_feed"],
                "published_at": a["published_at"] or None,
                "relevance_score": a["relevance_score"],
                "was_selected": a["was_selected"],
                "created_at": a["created_at"] or None,
            }
            for a in page_articles
        ],
    }


# ========== Projects ==========

@router.get("/projects")
def list_projects(db: SheetsDB = Depends(get_sheets_db)):
    """List all projects."""
    projects = db.get_all_projects()
    return [
        {
            "id": p["id"],
            "display_name": p["display_name"],
            "description": p["description"],
            "schedule_cron": p["schedule_cron"],
            "twitter_enabled": p["twitter_enabled"],
            "is_active": p["is_active"],
            "hashtags": p["hashtags"],
            "rss_feeds": p["rss_feeds"],
        }
        for p in projects
    ]


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: SheetsDB = Depends(get_sheets_db)):
    """Get full project configuration."""
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": p["id"],
        "display_name": p["display_name"],
        "description": p["description"],
        "brand_voice": p["brand_voice"],
        "hashtags": p["hashtags"],
        "rss_feeds": p["rss_feeds"],
        "scoring_weights": p["scoring_weights"],
        "schedule_cron": p["schedule_cron"],
        "twitter_enabled": p["twitter_enabled"],
        "is_active": p["is_active"],
    }


@router.put("/projects/{project_id}")
def update_project(project_id: str, update: ProjectUpdate, db: SheetsDB = Depends(get_sheets_db)):
    """Update project settings."""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    updates = {}
    if update.display_name is not None:
        updates["display_name"] = update.display_name
    if update.description is not None:
        updates["description"] = update.description
    if update.brand_voice is not None:
        updates["brand_voice"] = update.brand_voice
    if update.hashtags is not None:
        updates["hashtags"] = update.hashtags
    if update.rss_feeds is not None:
        updates["rss_feeds"] = update.rss_feeds
    if update.scoring_weights is not None:
        updates["scoring_weights"] = update.scoring_weights
    if update.schedule_cron is not None:
        updates["schedule_cron"] = update.schedule_cron
        add_project_schedule(project_id, update.schedule_cron)
    if update.twitter_enabled is not None:
        updates["twitter_enabled"] = update.twitter_enabled
    if update.is_active is not None:
        updates["is_active"] = update.is_active

    if updates:
        db.update_project(project_id, updates)

    return {"message": "Project updated", "project_id": project_id}


# ========== Profiles ==========

@router.get("/profiles")
def list_profiles(project_id: str = None, db: SheetsDB = Depends(get_sheets_db)):
    """List profiles for a project."""
    profiles = db.get_all_profiles(project_id=project_id)
    return [
        {
            "id": p["id"],
            "project_id": p["project_id"],
            "platform": p["platform"],
            "account_type": p["account_type"],
            "display_name": p["display_name"],
            "has_token": bool(p["access_token"]),
            "token_expires_at": p["token_expires_at"].isoformat() if p.get("token_expires_at") else None,
            "platform_user_id": p["platform_user_id"],
            "is_active": p["is_active"],
        }
        for p in profiles
    ]


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, update: ProfileUpdate, db: SheetsDB = Depends(get_sheets_db)):
    """Update profile settings."""
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    updates = {}
    if update.display_name is not None:
        updates["display_name"] = update.display_name
    if update.platform_user_id is not None:
        updates["platform_user_id"] = update.platform_user_id
    if update.access_token is not None:
        updates["access_token"] = update.access_token
    if update.refresh_token is not None:
        updates["refresh_token"] = update.refresh_token
    if update.is_active is not None:
        updates["is_active"] = update.is_active

    if updates:
        db.update_profile(profile_id, updates)

    return {"message": "Profile updated", "profile_id": profile_id}


@router.post("/profiles/disconnect/{project_id}/{platform}")
def disconnect_platform(project_id: str, platform: str, db: SheetsDB = Depends(get_sheets_db)):
    """Disconnect a platform from a project - clears all tokens."""
    profiles = db.get_all_profiles(project_id=project_id)
    platform_profiles = [p for p in profiles if p["platform"] == platform]
    if not platform_profiles:
        raise HTTPException(status_code=404, detail="No profiles found")

    for p in platform_profiles:
        updates = {
            "access_token": "",
            "refresh_token": "",
            "token_expires_at": "",
            "platform_user_id": "",
            "is_active": False,
        }
        if platform == "twitter":
            updates["extra_config"] = "{}"
        db.update_profile(p["id"], updates)

    if platform == "twitter":
        db.update_project(project_id, {"twitter_enabled": False})

    return {"message": f"{platform} disconnected from {project_id}"}


@router.put("/profiles/twitter/{project_id}")
def save_twitter_credentials(project_id: str, body: dict, db: SheetsDB = Depends(get_sheets_db)):
    """Save Twitter API credentials for a project."""
    api_key = body.get("api_key", "").strip()
    api_secret = body.get("api_secret", "").strip()
    access_token = body.get("access_token", "").strip()
    access_secret = body.get("access_secret", "").strip()

    if not all([api_key, api_secret, access_token, access_secret]):
        raise HTTPException(status_code=400, detail="All 4 Twitter credentials are required")

    profile = db.get_profile_by_keys(project_id, "twitter", "personal")
    if not profile:
        profile_id = db.insert_profile({
            "project_id": project_id,
            "platform": "twitter",
            "account_type": "personal",
            "display_name": f"{project_id} - Twitter",
        })
    else:
        profile_id = profile["id"]

    db.update_profile(profile_id, {
        "extra_config": json.dumps({
            "api_key": api_key,
            "api_secret": api_secret,
            "access_token": access_token,
            "access_secret": access_secret,
        }),
        "access_token": access_token,
        "is_active": True,
    })

    db.update_project(project_id, {"twitter_enabled": True})

    return {"message": f"Twitter connected for {project_id}"}


# ========== Metrics ==========

@router.get("/metrics")
def get_metrics(project_id: str = None, days: int = 30, db: SheetsDB = Depends(get_sheets_db)):
    """Get aggregated metrics."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.isoformat()

    runs = db.get_pipeline_runs(project_id=project_id)
    runs = [r for r in runs if r.get("started_at", "") >= since_iso]

    completed_runs = [r for r in runs if r["status"] != "running"]
    total = len(completed_runs)
    successful = sum(1 for r in completed_runs if r["status"] == "success")
    failed = sum(1 for r in completed_runs if r["status"] == "failed")
    partial = sum(1 for r in completed_runs if r["status"] == "partial_failure")
    fallback = sum(1 for r in completed_runs if r["used_fallback"])
    avg_articles = sum((r["articles_fetched"] or 0) for r in completed_runs) / max(total, 1)

    top_sources = db.get_top_sources(project_id=project_id, limit=5)

    return {
        "project_id": project_id or "all",
        "days": days,
        "total_runs": total,
        "successful_runs": successful,
        "failed_runs": failed,
        "partial_failures": partial,
        "fallback_count": fallback,
        "success_rate": round(successful / max(total, 1) * 100, 1),
        "avg_articles_per_run": round(avg_articles, 1),
        "top_sources": top_sources,
    }


# ========== Scheduler ==========

@router.get("/scheduler/jobs")
def list_scheduler_jobs():
    """List all scheduled jobs."""
    return get_all_jobs()


@router.get("/internal/export-tokens")
def export_tokens(secret: str = "", db: SheetsDB = Depends(get_sheets_db)):
    """Export LinkedIn tokens for persistence. Protected by CRON_SECRET."""
    settings = get_settings()
    if not settings.CRON_SECRET or secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    profiles = db.get_all_profiles()
    linkedin_profiles = [p for p in profiles if p["platform"] == "linkedin" and p["access_token"]]

    result = {}
    for p in linkedin_profiles:
        prefix = f"LINKEDIN_{p['project_id'].upper()}"
        if p["account_type"] == "personal" and p["platform_user_id"]:
            result[f"{prefix}_ACCESS_TOKEN"] = p["access_token"]
            result[f"{prefix}_REFRESH_TOKEN"] = p["refresh_token"] or ""
            result[f"{prefix}_USER_ID"] = p["platform_user_id"]
        elif p["account_type"] == "organization" and p["platform_user_id"]:
            result[f"{prefix}_ORG_ID"] = p["platform_user_id"]

    return result


@router.post("/scheduler/pause/{project_id}")
def pause_schedule(project_id: str):
    """Pause a project's schedule."""
    pause_project_schedule(project_id)
    return {"message": f"Schedule paused for {project_id}"}


@router.post("/scheduler/resume/{project_id}")
def resume_schedule(project_id: str):
    """Resume a project's schedule."""
    resume_project_schedule(project_id)
    return {"message": f"Schedule resumed for {project_id}"}


# ========== Helpers ==========

def _get_article_title(db: SheetsDB, article_id) -> str | None:
    if not article_id:
        return None
    article = db.get_article(article_id)
    return article["title"] if article else None
