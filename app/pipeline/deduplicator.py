"""Deduplicate articles against the database to avoid processing the same article twice."""
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode, parse_qs
from sqlalchemy.orm import Session
from app.models import Article

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
    db: Session,
) -> list[dict]:
    """Check articles against DB, insert new ones, return only unseen articles."""
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

    # Check which URLs already exist in DB
    urls = [a["url"] for a in unique_articles]
    existing_urls = set()

    # Query in batches to avoid SQLite variable limit
    batch_size = 500
    for i in range(0, len(urls), batch_size):
        batch = urls[i : i + batch_size]
        results = (
            db.query(Article.url)
            .filter(Article.project_id == project_id, Article.url.in_(batch))
            .all()
        )
        existing_urls.update(r[0] for r in results)

    # Filter to only new articles (not already in DB)
    new_articles = [a for a in unique_articles if a["url"] not in existing_urls]

    # Insert articles one at a time so a single bad article can't break the batch.
    # The pipeline_run was already committed, so rollbacks here are safe.
    inserted = 0
    for article in new_articles:
        try:
            db_article = Article(
                project_id=project_id,
                url=article["url"],
                original_url=article.get("original_url", article["url"]),
                title=(article.get("title", "") or "")[:500],
                source_feed=(article.get("source_feed", "") or "")[:200],
                summary=(article.get("summary", "") or "")[:2000],
                published_at=_parse_datetime(article.get("published_at")),
                fetch_run_id=pipeline_run_id,
            )
            db.add(db_article)
            db.flush()
            inserted += 1
        except Exception as e:
            logger.debug(f"Failed to insert article '{article.get('title', '')[:40]}': {e}")
            db.rollback()

    logger.info(
        f"Deduplication: {len(unique_articles)} unique, "
        f"{len(existing_urls)} already seen, {len(new_articles)} new, {inserted} inserted"
    )
    return new_articles


def _parse_datetime(val):
    """Convert ISO string or other date format to datetime object for SQLite."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
        ]:
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None
