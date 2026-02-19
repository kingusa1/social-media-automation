"""Main pipeline orchestrator - coordinates all 16 steps of the content automation workflow.

This is the core engine that replicates the full n8n workflow in Python.
Each step is wrapped in error handling with logging to pipeline_run.log_details.
"""
import json
import logging
import traceback
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import Project, Article, PipelineRun, GeneratedPost, PublishResult, Profile
from app.pipeline.rss_fetcher import fetch_feeds
from app.pipeline.url_resolver import resolve_urls, extract_source_from_url
from app.pipeline.deduplicator import deduplicate
from app.pipeline.scorer import score_articles, select_best
from app.pipeline.content_extractor import extract_article_content
from app.pipeline.ai_generator import generate_posts
from app.pipeline.post_parser import parse_ai_output
from app.pipeline.post_validator import validate_posts
from app.pipeline.fallback_templates import generate_fallback_posts

logger = logging.getLogger(__name__)


def run_pipeline(project_id: str, trigger_type: str, db: Session) -> PipelineRun:
    """Execute the full content automation pipeline for a project.

    Steps:
    1. Load project config
    2. Create pipeline_run record
    3. Fetch RSS feeds in parallel
    4. Resolve Google News redirect URLs
    5. Deduplicate against DB
    6. Score articles for relevance
    7. Select best article
    8. Fetch full article content
    9. Extract clean text
    10. Generate posts via AI
    11. Parse AI output
    12. Validate post quality
    13-15. Publish to social media
    16. Finalize and log
    """
    log_entries = []

    def log_step(step: str, status: str, message: str):
        entry = {
            "step": step,
            "status": status,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        log_entries.append(entry)
        level = {"success": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}.get(status, logging.INFO)
        logger.log(level, f"[{project_id}] {step}: {message}")

    # --- Step 1: Load project config ---
    project = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
    if not project:
        logger.error(f"Project {project_id} not found or inactive")
        raise ValueError(f"Project {project_id} not found or inactive")

    rss_feeds = json.loads(project.rss_feeds)
    scoring_weights = json.loads(project.scoring_weights)
    hashtags = json.loads(project.hashtags)

    # --- Step 2: Create pipeline_run record ---
    # Commit immediately so no rollback in later steps can wipe this record.
    pipeline_run = PipelineRun(
        project_id=project_id,
        trigger_type=trigger_type,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)
    log_step("init", "success", f"Pipeline started for {project.display_name} ({trigger_type})")

    try:
        # --- Step 3: Fetch RSS feeds ---
        try:
            raw_articles = fetch_feeds(rss_feeds)
            pipeline_run.articles_fetched = len(raw_articles)
            log_step("rss_fetch", "success", f"Fetched {len(raw_articles)} articles from {len(rss_feeds)} feeds")
        except Exception as e:
            log_step("rss_fetch", "error", f"RSS fetch failed: {e}")
            raw_articles = []

        if not raw_articles:
            # Try to use a recent unselected article from DB
            fallback_article = _get_fallback_article(project_id, db)
            if fallback_article:
                log_step("rss_fetch", "warning", "No new articles from RSS, using recent DB article as fallback")
                raw_articles = [_article_to_dict(fallback_article)]
            else:
                log_step("rss_fetch", "error", "No articles available from any source")
                pipeline_run.status = "failed"
                pipeline_run.error_message = "No articles available"
                pipeline_run.completed_at = datetime.now(timezone.utc)
                pipeline_run.log_details = json.dumps(log_entries)
                db.commit()
                return pipeline_run

        # --- Step 4: Resolve Google News URLs ---
        try:
            raw_articles = resolve_urls(raw_articles)
            log_step("url_resolve", "success", "URLs resolved")
        except Exception as e:
            log_step("url_resolve", "warning", f"URL resolution error (continuing): {e}")

        # --- Step 5: Deduplicate ---
        try:
            new_articles = deduplicate(raw_articles, project_id, pipeline_run.id, db)
            pipeline_run.articles_new = len(new_articles)
            log_step("dedup", "success", f"{len(new_articles)} new articles, {len(raw_articles) - len(new_articles)} duplicates removed")
        except Exception as e:
            log_step("dedup", "warning", f"Dedup error (using all articles): {e}")
            new_articles = raw_articles

        # If no new articles, use the raw articles (allow re-processing)
        articles_to_score = new_articles if new_articles else raw_articles

        # --- Step 6: Score articles ---
        try:
            scored_articles = score_articles(articles_to_score, scoring_weights)
            log_step("scoring", "success", f"Scored {len(scored_articles)} articles")
        except Exception as e:
            log_step("scoring", "warning", f"Scoring error: {e}")
            scored_articles = articles_to_score

        # --- Step 7: Select best article ---
        best_article = select_best(scored_articles)
        if not best_article:
            log_step("selection", "error", "No article could be selected")
            pipeline_run.status = "failed"
            pipeline_run.error_message = "No article selected"
            pipeline_run.completed_at = datetime.now(timezone.utc)
            pipeline_run.log_details = json.dumps(log_entries)
            db.commit()
            return pipeline_run

        article_title = best_article.get("title", "Industry Update")
        article_url = best_article.get("url", "")
        article_summary = best_article.get("summary", "")
        article_score = best_article.get("relevance_score", 0)
        log_step("selection", "success", f"Selected: '{article_title[:80]}' (score: {article_score})")

        # Mark as selected in DB
        db_article = db.query(Article).filter(
            Article.project_id == project_id,
            Article.url == article_url,
        ).first()
        if db_article:
            db_article.was_selected = True
            db_article.relevance_score = article_score
            pipeline_run.selected_article_id = db_article.id

        # --- Step 8 & 9: Fetch full article + extract text ---
        try:
            article_content = extract_article_content(
                url=article_url,
                title=article_title,
                summary=article_summary,
            )
            if db_article:
                db_article.content_text = article_content.text
            log_step("content_extract", "success",
                     f"Extracted {article_content.word_count} words via {article_content.extraction_method}")
        except Exception as e:
            log_step("content_extract", "warning", f"Content extraction failed: {e}")
            article_content = None

        content_text = article_content.text if article_content else article_summary

        # --- Step 10: Generate posts via AI ---
        linkedin_post = ""
        twitter_post = ""
        used_fallback = False
        ai_model = ""

        try:
            ai_result = generate_posts(
                article_title=article_title,
                article_url=article_url,
                article_description=article_summary,
                article_content=content_text,
                brand_voice=project.brand_voice,
            )
            if ai_result:
                ai_model = ai_result.model_used
                pipeline_run.ai_model_used = ai_model
                log_step("ai_generation", "success", f"Content generated using model: {ai_model}")

                # --- Step 11: Parse AI output ---
                parsed = parse_ai_output(ai_result.raw_output)
                linkedin_post = parsed.linkedin_post
                twitter_post = parsed.twitter_post
                log_step("parsing", "success",
                         f"Parsed - LinkedIn: {len(linkedin_post)} chars, Twitter: {len(twitter_post)} chars")
            else:
                log_step("ai_generation", "warning", "AI generation returned no content")
        except Exception as e:
            log_step("ai_generation", "error", f"AI generation failed: {e}")

        # --- Step 12: Validate posts ---
        if linkedin_post or twitter_post:
            try:
                validation = validate_posts(linkedin_post, twitter_post, hashtags)
                if validation.is_valid and validation.quality_score >= 70:
                    log_step("validation", "success", f"Posts valid (score: {validation.quality_score})")
                else:
                    log_step("validation", "warning",
                             f"Validation failed (score: {validation.quality_score}): {validation.errors}")
                    linkedin_post = ""
                    twitter_post = ""
            except Exception as e:
                log_step("validation", "warning", f"Validation error: {e}")

        # --- Step 13: Fallback if needed ---
        if not linkedin_post or not twitter_post:
            try:
                linkedin_post, twitter_post = generate_fallback_posts(
                    article_title=article_title,
                    article_url=article_url,
                    article_description=article_summary[:200] if article_summary else "",
                    project_id=project_id,
                )
                used_fallback = True
                pipeline_run.used_fallback = True
                log_step("fallback", "success", "Generated fallback template posts")
            except Exception as e:
                log_step("fallback", "error", f"Fallback generation failed: {e}")
                pipeline_run.status = "failed"
                pipeline_run.error_message = "Both AI and fallback post generation failed"
                pipeline_run.completed_at = datetime.now(timezone.utc)
                pipeline_run.log_details = json.dumps(log_entries)
                db.commit()
                return pipeline_run

        # Save generated posts to DB
        li_post_record = GeneratedPost(
            pipeline_run_id=pipeline_run.id,
            project_id=project_id,
            platform="linkedin",
            content=linkedin_post,
            article_url=article_url,
            article_title=article_title,
            is_fallback=used_fallback,
            quality_score=validation.quality_score if not used_fallback else 50.0,
        )
        tw_post_record = GeneratedPost(
            pipeline_run_id=pipeline_run.id,
            project_id=project_id,
            platform="twitter",
            content=twitter_post,
            article_url=article_url,
            article_title=article_title,
            is_fallback=used_fallback,
            quality_score=validation.quality_score if not used_fallback else 50.0,
        )
        db.add(li_post_record)
        db.add(tw_post_record)
        db.flush()

        # --- Steps 14-15: Publish to social media ---
        publish_success = 0
        publish_fail = 0

        # Publish LinkedIn posts
        linkedin_profiles = (
            db.query(Profile)
            .filter(
                Profile.project_id == project_id,
                Profile.platform == "linkedin",
                Profile.is_active == True,
            )
            .all()
        )

        for profile in linkedin_profiles:
            try:
                from app.publishers.linkedin_publisher import publish_to_linkedin
                result = publish_to_linkedin(linkedin_post, profile)
                pub_result = PublishResult(
                    generated_post_id=li_post_record.id,
                    profile_id=profile.id,
                    platform="linkedin",
                    account_type=profile.account_type,
                    status="success" if result.get("success") else "failed",
                    platform_post_id=result.get("post_id", ""),
                    error_message=result.get("error", ""),
                    posted_at=datetime.now(timezone.utc) if result.get("success") else None,
                )
                db.add(pub_result)
                if result.get("success"):
                    publish_success += 1
                    log_step(f"linkedin_{profile.account_type}", "success",
                             f"Posted to LinkedIn {profile.account_type}")
                else:
                    publish_fail += 1
                    log_step(f"linkedin_{profile.account_type}", "error",
                             f"LinkedIn {profile.account_type} failed: {result.get('error', 'Unknown')}")
            except Exception as e:
                publish_fail += 1
                pub_result = PublishResult(
                    generated_post_id=li_post_record.id,
                    profile_id=profile.id,
                    platform="linkedin",
                    account_type=profile.account_type,
                    status="failed",
                    error_message=str(e),
                )
                db.add(pub_result)
                log_step(f"linkedin_{profile.account_type}", "error", f"LinkedIn error: {e}")

        # Publish Twitter posts (if enabled)
        if project.twitter_enabled:
            try:
                from app.publishers.twitter_publisher import publish_to_twitter
                result = publish_to_twitter(twitter_post, project_id)
                pub_result = PublishResult(
                    generated_post_id=tw_post_record.id,
                    profile_id=0,
                    platform="twitter",
                    account_type="personal",
                    status="success" if result.get("success") else "failed",
                    platform_post_id=result.get("tweet_id", ""),
                    error_message=result.get("error", ""),
                    posted_at=datetime.now(timezone.utc) if result.get("success") else None,
                )
                db.add(pub_result)
                if result.get("success"):
                    publish_success += 1
                    log_step("twitter", "success", "Posted to Twitter")
                else:
                    publish_fail += 1
                    log_step("twitter", "error", f"Twitter failed: {result.get('error')}")
            except Exception as e:
                publish_fail += 1
                log_step("twitter", "error", f"Twitter error: {e}")
        else:
            log_step("twitter", "success", "Twitter posting disabled - skipped")

        if not linkedin_profiles:
            log_step("publishing", "warning", "No active LinkedIn profiles configured - posts saved but not published")

        # --- Step 16: Finalize ---
        if publish_fail > 0 and publish_success > 0:
            pipeline_run.status = "partial_failure"
        elif publish_fail > 0 and publish_success == 0 and linkedin_profiles:
            pipeline_run.status = "failed"
            pipeline_run.error_message = "All publish attempts failed"
        else:
            pipeline_run.status = "success"

        pipeline_run.completed_at = datetime.now(timezone.utc)
        pipeline_run.log_details = json.dumps(log_entries)
        log_step("finalize", "success",
                 f"Pipeline complete: {pipeline_run.status} "
                 f"(published: {publish_success}, failed: {publish_fail})")

        db.commit()
        return pipeline_run

    except Exception as e:
        log_step("fatal", "error", f"Unhandled error: {traceback.format_exc()}")
        pipeline_run.status = "failed"
        pipeline_run.error_message = str(e)
        pipeline_run.completed_at = datetime.now(timezone.utc)
        pipeline_run.log_details = json.dumps(log_entries)
        try:
            db.commit()
        except Exception:
            db.rollback()
        return pipeline_run


def _get_fallback_article(project_id: str, db: Session):
    """Get a recent unselected article from the DB as fallback."""
    return (
        db.query(Article)
        .filter(
            Article.project_id == project_id,
            Article.was_selected == False,
        )
        .order_by(Article.created_at.desc())
        .first()
    )


def _article_to_dict(article: Article) -> dict:
    """Convert an Article ORM model to a dict matching RawArticle format."""
    return {
        "url": article.url,
        "original_url": article.original_url or article.url,
        "title": article.title,
        "summary": article.summary or "",
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "source_feed": article.source_feed,
    }
