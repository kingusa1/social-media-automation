"""Main pipeline orchestrator - coordinates all steps of the content automation workflow.

Uses Google Sheets via SheetsDB for all data operations. Each write is immediately
persisted (no commits/rollbacks), fixing the crash issues from the old DB approach.
"""
import json
import logging
import traceback
from datetime import datetime, timezone

from app.sheets_db import SheetsDB
from app.pipeline.rss_fetcher import fetch_feeds
from app.pipeline.url_resolver import resolve_urls
from app.pipeline.deduplicator import deduplicate
from app.pipeline.scorer import score_articles, select_best
from app.pipeline.content_extractor import extract_article_content
from app.pipeline.ai_generator import generate_posts
from app.pipeline.post_parser import parse_ai_output
from app.pipeline.post_validator import validate_posts
from app.pipeline.fallback_templates import generate_fallback_posts

logger = logging.getLogger(__name__)


def run_pipeline(project_id: str, trigger_type: str, db: SheetsDB) -> dict:
    """Execute the full content automation pipeline for a project.

    Returns a dict (pipeline run record) with status, articles_fetched, etc.
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

    def _save_run(run_id: int, updates: dict):
        """Save log_entries + any status updates to the run."""
        updates["log_details"] = json.dumps(log_entries)
        try:
            db.update_pipeline_run(run_id, updates)
        except Exception as e:
            logger.error(f"Failed to update pipeline run {run_id}: {e}")

    # --- Step 1: Load project config ---
    project = db.get_project(project_id)
    if not project or not project["is_active"]:
        raise ValueError(f"Project {project_id} not found or inactive")

    rss_feeds = project["rss_feeds"]
    scoring_weights = project["scoring_weights"]
    hashtags = project["hashtags"]

    # --- Step 2: Create pipeline_run record (immediately persisted) ---
    run_id = db.insert_pipeline_run({
        "project_id": project_id,
        "trigger_type": trigger_type,
        "status": "running",
    })
    log_step("init", "success", f"Pipeline started for {project['display_name']} ({trigger_type})")

    try:
        # --- Step 3: Fetch RSS feeds ---
        try:
            raw_articles = fetch_feeds(rss_feeds)
            _save_run(run_id, {"articles_fetched": len(raw_articles)})
            log_step("rss_fetch", "success", f"Fetched {len(raw_articles)} articles from {len(rss_feeds)} feeds")
        except Exception as e:
            log_step("rss_fetch", "error", f"RSS fetch failed: {e}")
            raw_articles = []

        if not raw_articles:
            fallback_article = db.get_fallback_article(project_id)
            if fallback_article:
                log_step("rss_fetch", "warning", "No new articles from RSS, using recent DB article as fallback")
                raw_articles = [_article_to_dict(fallback_article)]
            else:
                log_step("rss_fetch", "error", "No articles available from any source")
                _save_run(run_id, {
                    "status": "failed",
                    "error_message": "No articles available",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
                return db.get_pipeline_run(run_id)

        # --- Step 4: URL resolution deferred ---
        log_step("url_resolve", "success", "URL resolution deferred to selected article only")

        # --- Step 5: Deduplicate ---
        try:
            new_articles = deduplicate(raw_articles, project_id, run_id, db)
            _save_run(run_id, {"articles_new": len(new_articles)})
            log_step("dedup", "success", f"{len(new_articles)} new, {len(raw_articles) - len(new_articles)} duplicates removed")
        except Exception as e:
            log_step("dedup", "warning", f"Dedup error (using all): {e}")
            new_articles = raw_articles

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
            _save_run(run_id, {
                "status": "failed",
                "error_message": "No article selected",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            return db.get_pipeline_run(run_id)

        article_title = best_article.get("title", "Industry Update")
        article_url = best_article.get("url", "")
        article_summary = best_article.get("summary", "")
        article_score = best_article.get("relevance_score", 0)
        log_step("selection", "success", f"Selected: '{article_title[:80]}' (score: {article_score})")

        # --- Step 4b: Resolve URL only for selected article ---
        try:
            resolved = resolve_urls([best_article])
            if resolved and resolved[0].get("url") != article_url:
                article_url = resolved[0]["url"]
                log_step("url_resolve", "success", f"Resolved URL to: {article_url[:80]}")
        except Exception as e:
            log_step("url_resolve", "warning", f"URL resolution skipped: {e}")

        # Mark as selected in sheets
        db_article = db.get_article_by_url(project_id, article_url)
        if db_article:
            db.update_article(db_article["id"], {
                "was_selected": True,
                "relevance_score": article_score,
            })
            _save_run(run_id, {"selected_article_id": db_article["id"]})

        # --- Step 8 & 9: Fetch full article + extract text ---
        try:
            article_content = extract_article_content(
                url=article_url, title=article_title, summary=article_summary,
            )
            if db_article:
                db.update_article(db_article["id"], {"content_text": article_content.text})
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
        quality_score = 0.0

        try:
            ai_result = generate_posts(
                article_title=article_title,
                article_url=article_url,
                article_description=article_summary,
                article_content=content_text,
                brand_voice=project["brand_voice"],
            )
            if ai_result:
                ai_model = ai_result.model_used
                _save_run(run_id, {"ai_model_used": ai_model})
                log_step("ai_generation", "success", f"Content generated using model: {ai_model}")

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
                quality_score = validation.quality_score
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
                quality_score = 50.0
                _save_run(run_id, {"used_fallback": True})
                log_step("fallback", "success", "Generated fallback template posts")
            except Exception as e:
                log_step("fallback", "error", f"Fallback generation failed: {e}")
                _save_run(run_id, {
                    "status": "failed",
                    "error_message": "Both AI and fallback post generation failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
                return db.get_pipeline_run(run_id)

        # Save generated posts
        li_post_id = db.insert_generated_post({
            "pipeline_run_id": run_id,
            "project_id": project_id,
            "platform": "linkedin",
            "content": linkedin_post,
            "article_url": article_url,
            "article_title": article_title,
            "is_fallback": used_fallback,
            "quality_score": quality_score,
        })
        tw_post_id = db.insert_generated_post({
            "pipeline_run_id": run_id,
            "project_id": project_id,
            "platform": "twitter",
            "content": twitter_post,
            "article_url": article_url,
            "article_title": article_title,
            "is_fallback": used_fallback,
            "quality_score": quality_score,
        })

        # --- Steps 14-15: Publish to social media ---
        publish_success = 0
        publish_fail = 0

        # Publish LinkedIn
        linkedin_profiles = db.get_active_profiles(project_id, "linkedin")
        for profile in linkedin_profiles:
            try:
                from app.publishers.linkedin_publisher import publish_to_linkedin
                result = publish_to_linkedin(linkedin_post, profile)
                db.insert_publish_result({
                    "generated_post_id": li_post_id,
                    "profile_id": profile["id"],
                    "platform": "linkedin",
                    "account_type": profile["account_type"],
                    "status": "success" if result.get("success") else "failed",
                    "platform_post_id": result.get("post_id", ""),
                    "error_message": result.get("error", ""),
                    "posted_at": datetime.now(timezone.utc).isoformat() if result.get("success") else "",
                })
                if result.get("success"):
                    publish_success += 1
                    log_step(f"linkedin_{profile['account_type']}", "success",
                             f"Posted to LinkedIn {profile['account_type']}")
                else:
                    publish_fail += 1
                    log_step(f"linkedin_{profile['account_type']}", "error",
                             f"LinkedIn {profile['account_type']} failed: {result.get('error', 'Unknown')}")
            except Exception as e:
                publish_fail += 1
                db.insert_publish_result({
                    "generated_post_id": li_post_id,
                    "profile_id": profile["id"],
                    "platform": "linkedin",
                    "account_type": profile["account_type"],
                    "status": "failed",
                    "error_message": str(e),
                })
                log_step(f"linkedin_{profile['account_type']}", "error", f"LinkedIn error: {e}")

        # Publish Twitter (if enabled)
        if project["twitter_enabled"]:
            try:
                from app.publishers.twitter_publisher import publish_to_twitter
                result = publish_to_twitter(twitter_post, project_id)
                db.insert_publish_result({
                    "generated_post_id": tw_post_id,
                    "profile_id": 0,
                    "platform": "twitter",
                    "account_type": "personal",
                    "status": "success" if result.get("success") else "failed",
                    "platform_post_id": result.get("tweet_id", ""),
                    "error_message": result.get("error", ""),
                    "posted_at": datetime.now(timezone.utc).isoformat() if result.get("success") else "",
                })
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
            log_step("publishing", "warning", "No active LinkedIn profiles - posts saved but not published")

        # --- Step 16: Finalize ---
        if publish_fail > 0 and publish_success > 0:
            final_status = "partial_failure"
        elif publish_fail > 0 and publish_success == 0 and linkedin_profiles:
            final_status = "failed"
        else:
            final_status = "success"

        _save_run(run_id, {
            "status": final_status,
            "error_message": "All publish attempts failed" if final_status == "failed" else "",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        log_step("finalize", "success",
                 f"Pipeline complete: {final_status} (published: {publish_success}, failed: {publish_fail})")

        return db.get_pipeline_run(run_id)

    except Exception as e:
        log_step("fatal", "error", f"Unhandled error: {traceback.format_exc()}")
        _save_run(run_id, {
            "status": "failed",
            "error_message": str(e)[:500],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return db.get_pipeline_run(run_id)


def _article_to_dict(article: dict) -> dict:
    """Convert a Sheets article dict to the RawArticle format expected by the pipeline."""
    return {
        "url": article.get("url", ""),
        "original_url": article.get("original_url", "") or article.get("url", ""),
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "published_at": article.get("published_at"),
        "source_feed": article.get("source_feed", ""),
    }
