"""Deduplicate articles against Google Sheets to avoid processing the same article twice."""
import logging
from urllib.parse import urlparse, urlencode, parse_qs

from app.sheets_db import SheetsDB

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Normalize URL for consistent deduplication."""
    try:
        parsed = urlparse(url)
        # Remove common tracking parameters
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
            "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
        }
        if parsed.query:
            params = parse_qs(parsed.query)
            cleaned = {k: v for k, v in params.items() if k.lower() not in tracking_params}
            query = urlencode(cleaned, doseq=True) if cleaned else ""
        else:
            query = ""

        # Rebuild URL without trailing slash and tracking params
        path = parsed.path.rstrip("/") or "/"
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if query:
            normalized += f"?{query}"
        return normalized
    except Exception:
        return url


def deduplicate(
    articles: list[dict],
    project_id: str,
    pipeline_run_id: int,
    db: SheetsDB,
) -> list[dict]:
    """Check articles against Sheets, insert new ones, return only unseen articles."""
    if not articles:
        return []

    # Normalize all URLs
    for article in articles:
        article["url"] = normalize_url(article["url"])

    # Remove articles with empty or duplicate URLs within this batch
    seen_urls = set()
    unique_articles = []
    for article in articles:
        if article["url"] and article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

    # Check which URLs already exist in Sheets
    urls = [a["url"] for a in unique_articles]
    existing_urls = db.get_existing_article_urls(project_id, urls)

    # Filter to only new articles (not already in Sheets)
    new_articles = [a for a in unique_articles if a["url"] not in existing_urls]

    # Batch insert all new articles at once
    if new_articles:
        articles_data = []
        for article in new_articles:
            articles_data.append({
                "project_id": project_id,
                "url": article["url"],
                "original_url": article.get("original_url", article["url"]),
                "title": (article.get("title", "") or "")[:500],
                "source_feed": (article.get("source_feed", "") or "")[:200],
                "summary": (article.get("summary", "") or "")[:2000],
                "published_at": article.get("published_at", ""),
                "fetch_run_id": pipeline_run_id,
            })
        try:
            db.insert_articles_batch(articles_data)
        except Exception as e:
            logger.warning(f"Batch insert failed, inserting one by one: {e}")
            for data in articles_data:
                try:
                    db.insert_article(data)
                except Exception as e2:
                    logger.debug(f"Failed to insert article '{data.get('title', '')[:40]}': {e2}")

    logger.info(
        f"Deduplication: {len(unique_articles)} unique, "
        f"{len(existing_urls)} already seen, {len(new_articles)} new"
    )
    return new_articles
