"""Pydantic schemas for API request/response validation."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ProjectResponse(BaseModel):
    id: str
    display_name: str
    description: str
    brand_voice: str
    hashtags: list[str]
    rss_feeds: list[str]
    scoring_weights: dict
    schedule_cron: str
    twitter_enabled: bool
    is_active: bool

    class Config:
        from_attributes = True


class ProjectUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    brand_voice: Optional[str] = None
    hashtags: Optional[list[str]] = None
    rss_feeds: Optional[list[str]] = None
    scoring_weights: Optional[dict] = None
    schedule_cron: Optional[str] = None
    twitter_enabled: Optional[bool] = None
    is_active: Optional[bool] = None


class ProfileResponse(BaseModel):
    id: int
    project_id: str
    platform: str
    account_type: str
    display_name: str
    has_token: bool
    token_expires_at: Optional[datetime] = None
    platform_user_id: str
    is_active: bool

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    platform_user_id: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    is_active: Optional[bool] = None


class PipelineRunResponse(BaseModel):
    id: int
    project_id: str
    trigger_type: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    articles_fetched: int
    articles_new: int
    ai_model_used: str
    used_fallback: bool
    error_message: str
    log_details: list[dict]
    selected_article_title: Optional[str] = None

    class Config:
        from_attributes = True


class GeneratedPostResponse(BaseModel):
    id: int
    pipeline_run_id: int
    project_id: str
    platform: str
    content: str
    article_url: str
    article_title: str
    is_fallback: bool
    quality_score: float
    created_at: datetime
    publish_statuses: list[dict] = []

    class Config:
        from_attributes = True


class ArticleResponse(BaseModel):
    id: int
    project_id: str
    url: str
    title: str
    source_feed: str
    published_at: Optional[datetime] = None
    relevance_score: float
    was_selected: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ManualTriggerRequest(BaseModel):
    project_id: str


class DashboardOverview(BaseModel):
    projects: list[dict]
    recent_runs: list[dict]
    total_articles: int
    total_posts: int


class MetricsResponse(BaseModel):
    project_id: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    fallback_count: int
    success_rate: float
    avg_articles_per_run: float
    top_sources: list[dict]
