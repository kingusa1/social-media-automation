"""Score articles for topic relevance using project-specific keyword weights.

Faithfully replicates the n8n workflow scoring algorithm with:
- Keyword matching in title and content
- Negative scoring for political content
- Combo bonuses for key topic intersections
- Recency scoring based on publication time
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def score_articles(articles: list[dict], scoring_config: dict) -> list[dict]:
    """Score each article and sort by relevance score (highest first)."""
    keywords = scoring_config.get("keywords", {})
    negative_keywords = scoring_config.get("negative_keywords", {})
    combo_bonuses = scoring_config.get("combo_bonuses", {})
    recency_hours = scoring_config.get("recency_hours", {"6": 5, "24": 2, "48": 0})
    base_score = scoring_config.get("base_score", 10)

    for article in articles:
        score = base_score
        title = (article.get("title") or "").lower()
        content = (article.get("summary") or "").lower()
        text = f"{title} {content}"

        # Negative scoring for political content
        for keyword, weight in negative_keywords.items():
            if keyword.lower() in text:
                score += weight  # weight is negative
                break  # One political hit is enough to penalize

        # Positive keyword scoring
        matched_categories = set()
        for keyword, weight in keywords.items():
            kw_lower = keyword.lower()
            if kw_lower in title:
                score += weight
                matched_categories.add(kw_lower.split()[0] if " " in kw_lower else kw_lower)
            elif kw_lower in content:
                score += weight * 0.7  # Content matches worth less than title matches
                matched_categories.add(kw_lower.split()[0] if " " in kw_lower else kw_lower)

        # Combo bonuses
        for combo_key, bonus in combo_bonuses.items():
            parts = combo_key.split("+")
            if all(any(p in cat for cat in matched_categories) for p in parts):
                score += bonus

        # Recency scoring
        pub_date = _parse_date(article.get("published_at"))
        if pub_date:
            hours_old = (datetime.now(timezone.utc) - pub_date).total_seconds() / 3600
            for threshold_str, bonus in sorted(recency_hours.items(), key=lambda x: int(x[0])):
                threshold = int(threshold_str)
                if hours_old < threshold:
                    score += bonus
                    break

        article["relevance_score"] = round(score, 2)

    # Sort by score descending, then by recency
    articles.sort(key=lambda a: (a.get("relevance_score", 0), a.get("published_at", "")), reverse=True)

    if articles:
        logger.info(
            f"Scored {len(articles)} articles. "
            f"Top: '{articles[0].get('title', 'N/A')[:60]}' (score: {articles[0].get('relevance_score', 0)})"
        )

    return articles


def select_best(articles: list[dict]) -> Optional[dict]:
    """Return the highest-scoring article."""
    if not articles:
        return None
    return articles[0]


def _parse_date(date_val) -> Optional[datetime]:
    """Parse various date formats to datetime."""
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        if date_val.tzinfo is None:
            return date_val.replace(tzinfo=timezone.utc)
        return date_val
    if isinstance(date_val, str):
        for fmt in [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
        ]:
            try:
                dt = datetime.strptime(date_val, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
    return None
