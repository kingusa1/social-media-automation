"""Resolve Google News redirect URLs to actual article URLs."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import requests

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def is_google_news_url(url: str) -> bool:
    """Check if URL is a Google News redirect."""
    return "news.google.com" in url


def resolve_urls(articles: list[dict]) -> list[dict]:
    """Resolve Google News redirect URLs in parallel."""
    google_news_articles = [a for a in articles if is_google_news_url(a["url"])]
    if not google_news_articles:
        return articles

    resolved_count = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_resolve_single_url, a["url"]): a
            for a in google_news_articles
        }
        for future in as_completed(futures):
            article = futures[future]
            try:
                resolved_url = future.result()
                if resolved_url != article["url"]:
                    article["original_url"] = article["url"]
                    article["url"] = resolved_url
                    resolved_count += 1
            except Exception as e:
                logger.debug(f"Could not resolve {article['url']}: {e}")

    logger.info(f"Resolved {resolved_count} Google News URLs")
    return articles


def _resolve_single_url(url: str) -> str:
    """Follow redirects to get the actual article URL."""
    try:
        # First try HEAD request with redirects
        resp = requests.head(
            url,
            headers={"User-Agent": BROWSER_USER_AGENT},
            allow_redirects=True,
            timeout=10,
        )
        final_url = resp.url

        # If we ended up at a non-Google domain, that's our article
        if not is_google_news_url(final_url):
            return final_url

        # Try GET with stream to catch JS redirects in meta tags
        resp = requests.get(
            url,
            headers={"User-Agent": BROWSER_USER_AGENT},
            allow_redirects=True,
            timeout=10,
            stream=True,
        )
        # Read just the first chunk for meta redirects
        content = next(resp.iter_content(chunk_size=4096), b"").decode("utf-8", errors="ignore")
        resp.close()

        # Look for meta refresh redirect
        meta_match = re.search(
            r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\'>\s]+)',
            content,
            re.IGNORECASE,
        )
        if meta_match:
            return meta_match.group(1)

        # Look for canonical link
        canonical_match = re.search(
            r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)',
            content,
            re.IGNORECASE,
        )
        if canonical_match and not is_google_news_url(canonical_match.group(1)):
            return canonical_match.group(1)

        return resp.url

    except Exception:
        return url


def extract_source_from_url(url: str) -> str:
    """Extract a human-readable source name from a URL."""
    if not url:
        return "News Source"
    try:
        hostname = urlparse(url).hostname or ""
        domain = hostname.replace("www.", "")

        source_map = {
            "salesforce.com": "Salesforce",
            "saleshacker.com": "Sales Hacker",
            "techcrunch.com": "TechCrunch",
            "theverge.com": "The Verge",
            "wired.com": "Wired",
            "zdnet.com": "ZDNet",
            "axios.com": "Axios",
            "devops.com": "DevOps.com",
            "thenewstack.io": "The New Stack",
            "infoq.com": "InfoQ",
            "kubernetes.io": "Kubernetes Blog",
            "hashicorp.com": "HashiCorp",
            "aws.amazon.com": "AWS",
            "cloud.google.com": "Google Cloud",
            "forbes.com": "Forbes",
            "news.google.com": "Google News",
        }

        for key, name in source_map.items():
            if key in domain:
                return name

        # Fallback: capitalize the domain name
        parts = domain.split(".")
        if parts:
            return parts[0].capitalize()
        return "News Source"
    except Exception:
        return "News Source"
