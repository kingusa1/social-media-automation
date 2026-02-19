"""SQLAlchemy ORM models for all database tables."""
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(50), primary_key=True)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    brand_voice = Column(Text, nullable=False)
    hashtags = Column(Text, nullable=False, default="[]")  # JSON array
    rss_feeds = Column(Text, nullable=False, default="[]")  # JSON array
    scoring_weights = Column(Text, nullable=False, default="{}")  # JSON dict
    schedule_cron = Column(String(100), nullable=False, default="0 9 * * 1-5")
    twitter_enabled = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    profiles = relationship("Profile", back_populates="project", cascade="all, delete-orphan")
    pipeline_runs = relationship("PipelineRun", back_populates="project", cascade="all, delete-orphan")
    articles = relationship("Article", back_populates="project", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "platform", "account_type", name="uq_profile"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(50), ForeignKey("projects.id"), nullable=False)
    platform = Column(String(20), nullable=False)  # "linkedin" or "twitter"
    account_type = Column(String(20), nullable=False)  # "personal" or "organization"
    display_name = Column(String(200), default="")
    access_token = Column(Text, default="")
    refresh_token = Column(Text, default="")
    token_expires_at = Column(DateTime, nullable=True)
    platform_user_id = Column(String(200), default="")  # LinkedIn URN or Twitter user ID
    extra_config = Column(Text, default="{}")  # JSON
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    project = relationship("Project", back_populates="profiles")
    publish_results = relationship("PublishResult", back_populates="profile")


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("project_id", "url", name="uq_article_url"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(50), ForeignKey("projects.id"), nullable=False)
    url = Column(String(2000), nullable=False)
    original_url = Column(String(2000), default="")
    title = Column(String(1000), default="")
    source_feed = Column(String(500), default="")
    summary = Column(Text, default="")
    published_at = Column(DateTime, nullable=True)
    relevance_score = Column(Float, default=0.0)
    was_selected = Column(Boolean, default=False)
    content_text = Column(Text, default="")
    fetch_run_id = Column(Integer, ForeignKey("pipeline_runs.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    project = relationship("Project", back_populates="articles")
    pipeline_run = relationship("PipelineRun", foreign_keys=[fetch_run_id])


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(50), ForeignKey("projects.id"), nullable=False)
    trigger_type = Column(String(20), nullable=False, default="manual")
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime, nullable=False, default=utcnow)
    completed_at = Column(DateTime, nullable=True)
    articles_fetched = Column(Integer, default=0)
    articles_new = Column(Integer, default=0)
    selected_article_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    ai_model_used = Column(String(100), default="")
    used_fallback = Column(Boolean, default=False)
    error_message = Column(Text, default="")
    log_details = Column(Text, default="[]")  # JSON array of step logs

    project = relationship("Project", back_populates="pipeline_runs")
    selected_article = relationship("Article", foreign_keys=[selected_article_id])
    generated_posts = relationship("GeneratedPost", back_populates="pipeline_run", cascade="all, delete-orphan")


class GeneratedPost(Base):
    __tablename__ = "generated_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_run_id = Column(Integer, ForeignKey("pipeline_runs.id"), nullable=False)
    project_id = Column(String(50), ForeignKey("projects.id"), nullable=False)
    platform = Column(String(20), nullable=False)  # "linkedin" or "twitter"
    content = Column(Text, nullable=False)
    article_url = Column(String(2000), default="")
    article_title = Column(String(1000), default="")
    is_fallback = Column(Boolean, default=False)
    quality_score = Column(Float, default=0.0)
    validation_notes = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    pipeline_run = relationship("PipelineRun", back_populates="generated_posts")
    publish_results = relationship("PublishResult", back_populates="generated_post", cascade="all, delete-orphan")


class PublishResult(Base):
    __tablename__ = "publish_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    generated_post_id = Column(Integer, ForeignKey("generated_posts.id"), nullable=False)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    platform = Column(String(20), nullable=False)
    account_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    platform_post_id = Column(String(500), default="")
    error_message = Column(Text, default="")
    posted_at = Column(DateTime, nullable=True)

    generated_post = relationship("GeneratedPost", back_populates="publish_results")
    profile = relationship("Profile", back_populates="publish_results")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(200), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
