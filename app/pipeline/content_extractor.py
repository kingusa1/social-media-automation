"""Fetch full article HTML and extract clean readable text.

Faithfully replicates the n8n 32_Extract_Insurance_Content node logic
with multiple extraction strategies for different blog platforms.
"""
import logging
import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


class ArticleContent:
    def __init__(self, title: str, text: str, url: str, extraction_method: str):
        self.title = title
        self.text = text
        self.url = url
        self.word_count = len(text.split()) if text else 0
        self.extraction_method = extraction_method


def extract_article_content(
    url: str,
    title: str = "",
    summary: str = "",
) -> ArticleContent:
    """Fetch and extract clean text from an article URL."""
    html = _fetch_html(url)

    if html:
        text = _extract_text_from_html(html)
        if text and len(text) > 100:
            return ArticleContent(
                title=title,
                text=text[:3000],
                url=url,
                extraction_method="html-extraction",
            )

    # Fallback: use RSS summary/description
    if summary and len(summary) > 50:
        clean_summary = _strip_html_tags(summary)
        if len(clean_summary) > 50:
            return ArticleContent(
                title=title,
                text=clean_summary[:3000],
                url=url,
                extraction_method="rss-summary",
            )

    # Generate contextual fallback from title
    fallback = _generate_title_fallback(title)
    return ArticleContent(
        title=title,
        text=fallback,
        url=url,
        extraction_method="generated-from-title",
    )


def _fetch_html(url: str) -> Optional[str]:
    """Fetch article HTML - fast single attempt for Vercel."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout=8,
            allow_redirects=True,
        )
        if resp.status_code < 400 and len(resp.text) > 100:
            return resp.text
    except Exception as e:
        logger.debug(f"Fetch failed for {url}: {e}")
    return None


def _extract_text_from_html(html: str) -> str:
    """Extract clean text from HTML using BeautifulSoup.

    Tries multiple content container selectors (article, main, various
    class-based containers) matching the n8n extraction strategies.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove unwanted elements
    for tag in soup.find_all(["script", "style", "noscript", "svg", "nav", "footer", "aside", "header"]):
        tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, type(soup.new_string(""))) and False):
        pass  # BeautifulSoup handles this

    # Try meta description as supplementary content
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if not meta_tag:
        meta_tag = soup.find("meta", attrs={"property": "og:description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"]

    # Strategy 1: Look for specific article containers
    content_selectors = [
        {"name": "article", "class_": re.compile(r"post", re.I)},
        {"name": "article"},
        {"name": "div", "class_": re.compile(r"post-content|entry-content|article-body|blog-post|content-body", re.I)},
        {"name": "main"},
        {"name": "div", "id": "content"},
        {"name": "div", "class_": re.compile(r"^content$", re.I)},
    ]

    content_elem = None
    for selector in content_selectors:
        elem = soup.find(**selector)
        if elem and len(elem.get_text(strip=True)) > 200:
            content_elem = elem
            break

    # Strategy 2: Find the largest text block
    if not content_elem:
        divs = soup.find_all("div")
        longest = ""
        longest_elem = None
        for div in divs:
            text = div.get_text(strip=True)
            if len(text) > len(longest) and len(text) > 200:
                longest = text
                longest_elem = div
        if longest_elem:
            content_elem = longest_elem

    # Extract text from the best element found, or body
    target = content_elem or soup.body or soup
    text = target.get_text(separator="\n", strip=True)

    # Clean up whitespace
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if len(line) > 20]  # Remove very short lines (nav remnants)
    text = "\n\n".join(lines)

    # If too short, prepend meta description
    if len(text) < 100 and meta_desc:
        text = meta_desc + "\n\n" + text

    # Truncate to ~3000 characters
    if len(text) > 3000:
        cut_point = text.rfind(".", 0, 2997)
        if cut_point > 2500:
            text = text[: cut_point + 1]
        else:
            text = text[:2997] + "..."

    return text.strip()


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags from a string."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator=" ", strip=True)


def _generate_title_fallback(title: str) -> str:
    """Generate contextual content from article title when extraction fails."""
    if not title:
        return (
            "Latest developments in business technology and automation are transforming "
            "how organizations operate. New innovations in AI, workflow automation, and "
            "strategic leadership are creating unprecedented opportunities."
        )

    keywords = title.lower()
    if "ai" in keywords or "artificial intelligence" in keywords:
        return (
            f"Breaking: {title}. This development in AI technology represents a critical "
            f"evolution in how businesses leverage artificial intelligence for automation, "
            f"sales, and customer engagement in an increasingly digital world."
        )
    elif "sales" in keywords or "crm" in keywords:
        return (
            f"Update: {title}. Sales technology and CRM innovations continue to reshape "
            f"how teams engage prospects, close deals, and drive revenue growth."
        )
    elif "devops" in keywords or "sre" in keywords or "kubernetes" in keywords:
        return (
            f"Update: {title}. DevOps and SRE practices continue to evolve, improving "
            f"system reliability, deployment velocity, and operational efficiency."
        )
    elif "automation" in keywords or "workflow" in keywords:
        return (
            f"Development: {title}. The automation and workflow optimization sector "
            f"continues to transform business operations, reducing manual effort "
            f"and enabling teams to focus on strategic initiatives."
        )
    else:
        return (
            f"Industry Update: {title}. This development highlights the ongoing "
            f"transformation in business practices, technology adoption, and "
            f"operational excellence across the industry."
        )
