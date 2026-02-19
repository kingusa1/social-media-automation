"""Database engine, session factory, and initialization."""
import json
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Build engine kwargs based on database type
engine_kwargs = {"echo": False}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

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
