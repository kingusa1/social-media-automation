"""Fetch and parse RSS feeds in parallel."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import TypedDict, Optional
import feedparser
import requests

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class RawArticle(TypedDict):
    url: str
    original_url: str
    title: str
    summary: str
    published_at: Optional[str]
    source_feed: str


def fetch_feeds(feed_urls: list[str], timeout: int = 30) -> list[RawArticle]:
    """Fetch all RSS feeds in parallel and return merged article list."""
    articles = []
    failed_feeds = 0

    with ThreadPoolExecutor(max_workers=min(len(feed_urls), 7)) as executor:
        futures = {
            executor.submit(_fetch_single_feed, url, timeout): url
            for url in feed_urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                result = future.result()
                articles.extend(result)
                logger.info(f"Fetched {len(result)} articles from {url}")
            except Exception as e:
                failed_feeds += 1
                logger.warning(f"Failed to fetch {url}: {e}")

    logger.info(
        f"RSS fetch complete: {len(articles)} articles from "
        f"{len(feed_urls) - failed_feeds}/{len(feed_urls)} feeds"
    )
    return articles


def _fetch_single_feed(url: str, timeout: int) -> list[RawArticle]:
    """Parse a single RSS feed with retry."""
    for attempt in range(3):
        try:
            # feedparser can handle URLs directly, but we fetch manually
            # for better timeout/user-agent control
            resp = requests.get(
                url,
                headers={"User-Agent": BROWSER_USER_AGENT},
                timeout=timeout,
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            if feed.bozo and not feed.entries:
                raise ValueError(f"Feed parse error: {feed.bozo_exception}")

            articles = []
            for entry in feed.entries:
                link = entry.get("link", "")
                if not link:
                    continue

                # Parse published date
                pub_date = None
                for date_field in ["published_parsed", "updated_parsed"]:
                    parsed = entry.get(date_field)
                    if parsed:
                        try:
                            pub_date = datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
                        except Exception:
                            pass
                        break

                # Get best summary
                summary = ""
                if entry.get("summary"):
                    summary = entry["summary"]
                elif entry.get("description"):
                    summary = entry["description"]
                elif entry.get("content"):
                    # Some feeds use content:encoded
                    if isinstance(entry["content"], list) and entry["content"]:
                        summary = entry["content"][0].get("value", "")

                articles.append(RawArticle(
                    url=link,
                    original_url=link,
                    title=entry.get("title", ""),
                    summary=summary[:2000],  # Cap summary length
                    published_at=pub_date,
                    source_feed=url,
                ))

            return articles

        except Exception as e:
            if attempt < 2:
                logger.debug(f"Retry {attempt + 1} for {url}: {e}")
                import time
                time.sleep(3)
            else:
                raise
    return []
