"""Database engine, session factory, and initialization."""
import json
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Build engine kwargs based on database type
engine_kwargs = {"echo": False}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif settings.DATABASE_URL.startswith("postgresql"):
    # PostgreSQL pool settings for Neon/Vercel serverless
    engine_kwargs["pool_size"] = 3
    engine_kwargs["max_overflow"] = 5
    engine_kwargs["pool_recycle"] = 300  # recycle connections every 5 min
    engine_kwargs["pool_pre_ping"] = True  # verify connections before use

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and seed project configs if empty."""
    from app.models import Project, Profile  # noqa: avoid circular import
    Base.metadata.create_all(bind=engine)
    seed_projects()
    # Only restore LinkedIn tokens from env vars when using SQLite
    # (PostgreSQL via Neon persists tokens across cold starts)
    if not settings.is_postgres:
        _restore_linkedin_tokens()


def seed_projects():
    """Seed projects from JSON config files if they don't exist in DB."""
    from app.models import Project, Profile

    config_dir = Path(__file__).parent.parent / "project_configs"
    if not config_dir.exists():
        return

    db = SessionLocal()
    try:
        for config_file in config_dir.glob("*.json"):
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            project_id = config["id"]
            existing = db.query(Project).filter(Project.id == project_id).first()
            if existing:
                continue

            project = Project(
                id=project_id,
                display_name=config["display_name"],
                description=config.get("description", ""),
                brand_voice=config["brand_voice"],
                hashtags=json.dumps(config.get("hashtags", [])),
                rss_feeds=json.dumps(config.get("rss_feeds", [])),
                scoring_weights=json.dumps(config.get("scoring_weights", {})),
                schedule_cron=config.get("schedule_cron", "0 9 * * 1-5"),
                twitter_enabled=config.get("twitter_enabled", False),
                is_active=True,
            )
            db.add(project)

            # Create default profile placeholders
            for platform in ["linkedin"]:
                for account_type in ["personal", "organization"]:
                    profile = Profile(
                        project_id=project_id,
                        platform=platform,
                        account_type=account_type,
                        display_name=f"{config['display_name']} - {account_type.title()} LinkedIn",
                        is_active=False,  # inactive until credentials added
                    )
                    db.add(profile)

        db.commit()
        logger.info("Projects seeded successfully")
    except Exception as e:
        db.rollback()
        logger.warning(f"Error seeding projects: {e}")
    finally:
        db.close()


def _restore_linkedin_tokens():
    """Restore LinkedIn tokens from env vars after Vercel cold starts (SQLite only)."""
    from app.models import Project
    from app.publishers.linkedin_auth import load_tokens_from_env

    db = SessionLocal()
    try:
        projects = db.query(Project).filter(Project.is_active == True).all()
        for project in projects:
            load_tokens_from_env(project.id, db)
    except Exception as e:
        logger.warning(f"Error restoring LinkedIn tokens: {e}")
    finally:
        db.close()
