"""Filter articles to English-only by detecting non-Latin characters in titles."""
import re
import logging

logger = logging.getLogger(__name__)

# Characters that indicate non-English content
# CJK Unified Ideographs, Hiragana, Katakana, Hangul, Arabic, Devanagari, Thai, etc.
NON_LATIN_PATTERN = re.compile(
    r'[\u4e00-\u9fff'   # CJK (Chinese)
    r'\u3040-\u309f'    # Hiragana (Japanese)
    r'\u30a0-\u30ff'    # Katakana (Japanese)
    r'\uac00-\ud7af'    # Hangul (Korean)
    r'\u0600-\u06ff'    # Arabic
    r'\u0900-\u097f'    # Devanagari (Hindi)
    r'\u0e00-\u0e7f'    # Thai
    r'\u0400-\u04ff'    # Cyrillic (Russian)
    r']'
)


def is_english(text: str) -> bool:
    """Check if text is likely English by looking for non-Latin script characters.

    Returns True if the text appears to be English (no significant non-Latin chars).
    """
    if not text:
        return True  # empty = allow through

    # Count non-Latin characters
    non_latin_chars = len(NON_LATIN_PATTERN.findall(text))

    # If more than 2 non-Latin characters in the title, it's probably not English
    if non_latin_chars > 2:
        return False

    # Also check ratio — if >20% of chars are non-Latin, not English
    if len(text) > 0 and non_latin_chars / len(text) > 0.2:
        return False

    return True


def filter_english_only(articles: list[dict]) -> list[dict]:
    """Filter a list of articles to only include English-language ones.

    Checks the title (and summary if available) for non-Latin script characters.
    """
    english_articles = []
    filtered_count = 0

    for article in articles:
        title = article.get("title", "")
        summary = article.get("summary", "")

        # Check title first (most reliable indicator)
        if not is_english(title):
            filtered_count += 1
            continue

        # Also check summary for non-English content
        if summary and not is_english(summary[:200]):
            filtered_count += 1
            continue

        english_articles.append(article)

    if filtered_count > 0:
        logger.info(f"Language filter: kept {len(english_articles)}, removed {filtered_count} non-English articles")

    return english_articles
