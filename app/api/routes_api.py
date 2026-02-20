"""REST API endpoints for the dashboard (JSON responses)."""
import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.config import get_settings
from app.database import get_db

logger = logging.getLogger(__name__)
from app.models import Project, Profile, PipelineRun, GeneratedPost, PublishResult, Article
from app.schemas import (
    ProjectResponse, ProjectUpdate, ProfileResponse, ProfileUpdate,
    ManualTriggerRequest, DashboardOverview, MetricsResponse,
    PipelineRunResponse, GeneratedPostResponse, ArticleResponse,
)
from app.scheduler.scheduler import (
    get_all_jobs, get_next_run_time, add_project_schedule,
    pause_project_schedule, resume_project_schedule,
)

router = APIRouter()


# ========== Dashboard Overview ==========

@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    """Get dashboard overview for all projects with connection status."""
    try:
        # Auto-cleanup stuck runs (running > 10 min = timed out)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.query(PipelineRun).filter(
            PipelineRun.status == "running",
            PipelineRun.started_at < cutoff,
        ).update({
            PipelineRun.status: "failed",
            PipelineRun.error_message: "Timed out",
            PipelineRun.completed_at: datetime.now(timezone.utc),
        })
        db.commit()
    except Exception as e:
        logger.warning(f"Cleanup stuck runs failed: {e}")
        db.rollback()

    projects = db.query(Project).all()
    project_data = []

    for p in projects:
        last_run = (
            db.query(PipelineRun)
            .filter(PipelineRun.project_id == p.id)
            .order_by(desc(PipelineRun.started_at))
            .first()
        )
        try:
            next_run = get_next_run_time(p.id)
        except Exception:
            next_run = None
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        today_posts = (
            db.query(GeneratedPost)
            .filter(GeneratedPost.project_id == p.id, GeneratedPost.created_at >= today_start)
            .count()
        )
        total_posts = db.query(GeneratedPost).filter(GeneratedPost.project_id == p.id).count()
        total_articles = db.query(Article).filter(Article.project_id == p.id).count()
        total_runs = db.query(PipelineRun).filter(PipelineRun.project_id == p.id).count()
        success_runs = db.query(PipelineRun).filter(
            PipelineRun.project_id == p.id, PipelineRun.status == "success"
        ).count()

        # Connection status
        profiles = db.query(Profile).filter(Profile.project_id == p.id).all()
        linkedin_connected = any(pr.platform == "linkedin" and pr.access_token for pr in profiles)
        twitter_connected = any(pr.platform == "twitter" and pr.access_token for pr in profiles)

        project_data.append({
            "id": p.id,
            "display_name": p.display_name,
            "is_active": p.is_active,
            "twitter_enabled": p.twitter_enabled,
            "linkedin_connected": linkedin_connected,
            "twitter_connected": twitter_connected,
            "last_run": {
                "status": last_run.status if last_run else "never",
                "time": last_run.started_at.isoformat() if last_run else None,
                "used_fallback": last_run.used_fallback if last_run else False,
            } if last_run else None,
            "next_run": next_run.isoformat() if next_run else None,
            "today_posts": today_posts,
            "total_posts": total_posts,
            "total_articles": total_articles,
            "total_runs": total_runs,
            "success_runs": success_runs,
        })

    recent_runs = (
        db.query(PipelineRun)
        .order_by(desc(PipelineRun.started_at))
        .limit(10)
        .all()
    )

    return {
        "projects": project_data,
        "recent_runs": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "status": r.status,
                "trigger_type": r.trigger_type,
                "started_at": r.started_at.isoformat(),
                "used_fallback": r.used_fallback,
            }
            for r in recent_runs
        ],
    }


# ========== Pipeline Runs ==========

@router.get("/runs")
def list_runs(
    project_id: str = None,
    page: int = 1,
    per_page: int = 20,
    db: Session = Depends(get_db),
):
    """List pipeline runs with pagination."""
    query = db.query(PipelineRun)
    if project_id:
        query = query.filter(PipelineRun.project_id == project_id)
    query = query.order_by(desc(PipelineRun.started_at))

    total = query.count()
    runs = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "runs": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "trigger_type": r.trigger_type,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "articles_fetched": r.articles_fetched,
                "articles_new": r.articles_new,
                "ai_model_used": r.ai_model_used,
                "used_fallback": r.used_fallback,
                "error_message": r.error_message,
                "selected_article_title": r.selected_article.title if r.selected_article else None,
            }
            for r in runs
        ],
    }


@router.get("/runs/{run_id}")
def get_run_detail(run_id: int, db: Session = Depends(get_db)):
    """Get detailed info for a single pipeline run."""
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    posts = db.query(GeneratedPost).filter(GeneratedPost.pipeline_run_id == run_id).all()

    return {
        "id": run.id,
        "project_id": run.project_id,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "articles_fetched": run.articles_fetched,
        "articles_new": run.articles_new,
        "ai_model_used": run.ai_model_used,
        "used_fallback": run.used_fallback,
        "error_message": run.error_message,
        "log_details": json.loads(run.log_details) if run.log_details else [],
        "selected_article": {
            "title": run.selected_article.title,
            "url": run.selected_article.url,
            "score": run.selected_article.relevance_score,
        } if run.selected_article else None,
        "posts": [
            {
                "id": p.id,
                "platform": p.platform,
                "content": p.content,
                "is_fallback": p.is_fallback,
                "quality_score": p.quality_score,
                "publish_results": [
                    {
                        "platform": pr.platform,
                        "account_type": pr.account_type,
                        "status": pr.status,
                        "error_message": pr.error_message,
                    }
                    for pr in p.publish_results
                ],
            }
            for p in posts
        ],
    }


@router.post("/runs/trigger")
def trigger_pipeline(request: ManualTriggerRequest, db: Session = Depends(get_db)):
    """Manually trigger a pipeline run for a project."""
    project = db.query(Project).filter(Project.id == request.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if a run is already in progress
    running = (
        db.query(PipelineRun)
        .filter(PipelineRun.project_id == request.project_id, PipelineRun.status == "running")
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")

    settings = get_settings()

    if settings.is_vercel:
        # Vercel serverless: run synchronously (threads get killed after response)
        from app.pipeline.orchestrator import run_pipeline
        try:
            result = run_pipeline(request.project_id, trigger_type="manual", db=db)
            return {
                "message": f"Pipeline completed for {project.display_name}",
                "project_id": request.project_id,
                "status": result.status,
                "articles_fetched": result.articles_fetched,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Local: run in background thread for non-blocking UX
        from app.database import SessionLocal

        def _run():
            session = SessionLocal()
            try:
                from app.pipeline.orchestrator import run_pipeline
                result = run_pipeline(request.project_id, trigger_type="manual", db=session)
                logger.info(f"Manual pipeline for {request.project_id} completed: {result.status}")
            except Exception as e:
                logger.error(f"Manual pipeline for {request.project_id} failed: {e}", exc_info=True)
            finally:
                session.close()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {"message": f"Pipeline triggered for {project.display_name}", "project_id": request.project_id}


# ========== Generated Posts ==========

@router.get("/posts")
def list_posts(
    project_id: str = None,
    page: int = 1,
    per_page: int = 20,
    db: Session = Depends(get_db),
):
    """List generated posts with pagination."""
    query = db.query(GeneratedPost)
    if project_id:
        query = query.filter(GeneratedPost.project_id == project_id)
    query = query.order_by(desc(GeneratedPost.created_at))

    total = query.count()
    posts = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "posts": [
            {
                "id": p.id,
                "pipeline_run_id": p.pipeline_run_id,
                "project_id": p.project_id,
                "platform": p.platform,
                "content": p.content,
                "article_url": p.article_url,
                "article_title": p.article_title,
                "is_fallback": p.is_fallback,
                "quality_score": p.quality_score,
                "created_at": p.created_at.isoformat(),
                "publish_results": [
                    {
                        "account_type": pr.account_type,
                        "status": pr.status,
                        "error_message": pr.error_message,
                    }
                    for pr in p.publish_results
                ],
            }
            for p in posts
        ],
    }


# ========== Articles ==========

@router.get("/articles")
def list_articles(
    project_id: str = None,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
):
    """List articles with scores."""
    query = db.query(Article)
    if project_id:
        query = query.filter(Article.project_id == project_id)
    query = query.order_by(desc(Article.created_at))

    total = query.count()
    articles = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "articles": [
            {
                "id": a.id,
                "project_id": a.project_id,
                "url": a.url,
                "title": a.title,
                "source_feed": a.source_feed,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "relevance_score": a.relevance_score,
                "was_selected": a.was_selected,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in articles
        ],
    }


# ========== Projects ==========

@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    """List all projects."""
    projects = db.query(Project).all()
    return [
        {
            "id": p.id,
            "display_name": p.display_name,
            "description": p.description,
            "schedule_cron": p.schedule_cron,
            "twitter_enabled": p.twitter_enabled,
            "is_active": p.is_active,
            "hashtags": json.loads(p.hashtags),
            "rss_feeds": json.loads(p.rss_feeds),
        }
        for p in projects
    ]


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    """Get full project configuration."""
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": p.id,
        "display_name": p.display_name,
        "description": p.description,
        "brand_voice": p.brand_voice,
        "hashtags": json.loads(p.hashtags),
        "rss_feeds": json.loads(p.rss_feeds),
        "scoring_weights": json.loads(p.scoring_weights),
        "schedule_cron": p.schedule_cron,
        "twitter_enabled": p.twitter_enabled,
        "is_active": p.is_active,
    }


@router.put("/projects/{project_id}")
def update_project(project_id: str, update: ProjectUpdate, db: Session = Depends(get_db)):
    """Update project settings."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if update.display_name is not None:
        project.display_name = update.display_name
    if update.description is not None:
        project.description = update.description
    if update.brand_voice is not None:
        project.brand_voice = update.brand_voice
    if update.hashtags is not None:
        project.hashtags = json.dumps(update.hashtags)
    if update.rss_feeds is not None:
        project.rss_feeds = json.dumps(update.rss_feeds)
    if update.scoring_weights is not None:
        project.scoring_weights = json.dumps(update.scoring_weights)
    if update.schedule_cron is not None:
        project.schedule_cron = update.schedule_cron
        add_project_schedule(project_id, update.schedule_cron)
    if update.twitter_enabled is not None:
        project.twitter_enabled = update.twitter_enabled
    if update.is_active is not None:
        project.is_active = update.is_active

    db.commit()
    return {"message": "Project updated", "project_id": project_id}


# ========== Profiles ==========

@router.get("/profiles")
def list_profiles(project_id: str = None, db: Session = Depends(get_db)):
    """List profiles for a project."""
    query = db.query(Profile)
    if project_id:
        query = query.filter(Profile.project_id == project_id)
    profiles = query.all()
    return [
        {
            "id": p.id,
            "project_id": p.project_id,
            "platform": p.platform,
            "account_type": p.account_type,
            "display_name": p.display_name,
            "has_token": bool(p.access_token),
            "token_expires_at": p.token_expires_at.isoformat() if p.token_expires_at else None,
            "platform_user_id": p.platform_user_id,
            "is_active": p.is_active,
        }
        for p in profiles
    ]


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, update: ProfileUpdate, db: Session = Depends(get_db)):
    """Update profile settings."""
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if update.display_name is not None:
        profile.display_name = update.display_name
    if update.platform_user_id is not None:
        profile.platform_user_id = update.platform_user_id
    if update.access_token is not None:
        profile.access_token = update.access_token
    if update.refresh_token is not None:
        profile.refresh_token = update.refresh_token
    if update.is_active is not None:
        profile.is_active = update.is_active

    db.commit()
    return {"message": "Profile updated", "profile_id": profile_id}


@router.post("/profiles/disconnect/{project_id}/{platform}")
def disconnect_platform(project_id: str, platform: str, db: Session = Depends(get_db)):
    """Disconnect a platform from a project - clears all tokens."""
    profiles = (
        db.query(Profile)
        .filter(Profile.project_id == project_id, Profile.platform == platform)
        .all()
    )
    if not profiles:
        raise HTTPException(status_code=404, detail="No profiles found")

    for p in profiles:
        p.access_token = ""
        p.refresh_token = ""
        p.token_expires_at = None
        p.platform_user_id = ""
        p.is_active = False
        if platform == "twitter":
            p.extra_config = "{}"

    # If disconnecting twitter, also disable twitter on the project
    if platform == "twitter":
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            project.twitter_enabled = False

    db.commit()
    return {"message": f"{platform} disconnected from {project_id}"}


@router.put("/profiles/twitter/{project_id}")
def save_twitter_credentials(project_id: str, body: dict, db: Session = Depends(get_db)):
    """Save Twitter API credentials for a project."""
    api_key = body.get("api_key", "").strip()
    api_secret = body.get("api_secret", "").strip()
    access_token = body.get("access_token", "").strip()
    access_secret = body.get("access_secret", "").strip()

    if not all([api_key, api_secret, access_token, access_secret]):
        raise HTTPException(status_code=400, detail="All 4 Twitter credentials are required")

    # Get or create the twitter profile for this project
    profile = (
        db.query(Profile)
        .filter(
            Profile.project_id == project_id,
            Profile.platform == "twitter",
            Profile.account_type == "personal",
        )
        .first()
    )
    if not profile:
        profile = Profile(
            project_id=project_id,
            platform="twitter",
            account_type="personal",
            display_name=f"{project_id} - Twitter",
        )
        db.add(profile)

    # Store credentials in extra_config JSON
    profile.extra_config = json.dumps({
        "api_key": api_key,
        "api_secret": api_secret,
        "access_token": access_token,
        "access_secret": access_secret,
    })
    profile.access_token = access_token  # Mark as "has token"
    profile.is_active = True

    # Enable twitter on the project
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.twitter_enabled = True

    db.commit()
    return {"message": f"Twitter connected for {project_id}"}


# ========== Metrics ==========

@router.get("/metrics")
def get_metrics(project_id: str = None, days: int = 30, db: Session = Depends(get_db)):
    """Get aggregated metrics."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    query = db.query(PipelineRun).filter(PipelineRun.started_at >= since)
    if project_id:
        query = query.filter(PipelineRun.project_id == project_id)

    # Exclude still-running entries from completed metrics
    runs = query.all()
    completed_runs = [r for r in runs if r.status != "running"]
    total = len(completed_runs)
    successful = sum(1 for r in completed_runs if r.status == "success")
    failed = sum(1 for r in completed_runs if r.status == "failed")
    partial = sum(1 for r in completed_runs if r.status == "partial_failure")
    fallback = sum(1 for r in completed_runs if r.used_fallback)
    avg_articles = sum((r.articles_fetched or 0) for r in completed_runs) / max(total, 1)

    # Top sources
    source_query = db.query(Article.source_feed, func.count(Article.id).label("count"))
    if project_id:
        source_query = source_query.filter(Article.project_id == project_id)
    source_query = source_query.filter(Article.was_selected == True)
    sources = source_query.group_by(Article.source_feed).order_by(desc("count")).limit(5).all()

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
        "top_sources": [{"source": s[0], "count": s[1]} for s in sources],
    }


# ========== Scheduler ==========

@router.get("/scheduler/jobs")
def list_scheduler_jobs():
    """List all scheduled jobs."""
    return get_all_jobs()


@router.get("/internal/export-tokens")
def export_tokens(secret: str = "", db: Session = Depends(get_db)):
    """Export LinkedIn tokens for persistence. Protected by CRON_SECRET."""
    settings = get_settings()
    if not settings.CRON_SECRET or secret != settings.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    profiles = db.query(Profile).filter(
        Profile.platform == "linkedin",
        Profile.access_token != "",
    ).all()

    result = {}
    for p in profiles:
        prefix = f"LINKEDIN_{p.project_id.upper()}"
        if p.account_type == "personal" and p.platform_user_id:
            result[f"{prefix}_ACCESS_TOKEN"] = p.access_token
            result[f"{prefix}_REFRESH_TOKEN"] = p.refresh_token or ""
            result[f"{prefix}_USER_ID"] = p.platform_user_id
        elif p.account_type == "organization" and p.platform_user_id:
            result[f"{prefix}_ORG_ID"] = p.platform_user_id

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
