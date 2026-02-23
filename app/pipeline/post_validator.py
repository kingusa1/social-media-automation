"""Validate and sanitize social media posts before publishing.

Ensures posts are clean, professional, and free of HTML, URLs, broken text,
non-English content, and common AI generation artifacts.
"""
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# URL/link pattern
_URL_RE = re.compile(r'https?://\S+|www\.\S+|bit\.ly/\S+', re.IGNORECASE)
# HTML entities
_HTML_ENTITY_RE = re.compile(r'&(?:amp|lt|gt|quot|nbsp|#\d+|#x[0-9a-f]+);', re.IGNORECASE)
# Detect any HTML (complete or partial tags, attributes)
_HTML_DETECT_RE = re.compile(r'<[a-zA-Z/][^>]*>?|(?:class|src|alt|href|style)=["\']', re.IGNORECASE)


class ValidationResult:
    def __init__(self):
        self.is_valid = True
        self.quality_score = 100.0
        self.errors: list[str] = []
        self.warnings: list[str] = []


def strip_html(text: str) -> str:
    """Strip HTML from source data (RSS summaries, descriptions).

    Uses BeautifulSoup for bulletproof HTML removal. Use this on raw source
    data BEFORE it enters templates, NOT on assembled posts.
    """
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def sanitize_post(text: str) -> str:
    """Final safety net: strip any HTML tags, entities, and URLs from a post.

    Called on EVERY post (AI-generated and fallback) right before publishing.
    Uses targeted regex that removes HTML without eating surrounding text.
    """
    if not text:
        return text

    clean = text

    # 1. Remove complete HTML tags: <div>, <img src="...">, </span>, <br/>, etc.
    clean = re.sub(r'</?[a-zA-Z][a-zA-Z0-9]*\b[^>]*/?\s*>', '', clean)

    # 2. Remove incomplete/truncated HTML tags (known tag names without closing >)
    _KNOWN_TAGS = r'div|span|img|a|p|br|h[1-6]|ul|ol|li|table|tr|td|th|iframe|script|style|link|meta|section|article|header|footer|nav|figure|figcaption|source|video|audio'
    clean = re.sub(r'<(?:' + _KNOWN_TAGS + r')\b[^>\n]*', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'</(?:' + _KNOWN_TAGS + r')\b[^>\n]*', '', clean, flags=re.IGNORECASE)

    # 3. Remove leaked HTML attribute fragments: alt="...", class="...", src="..."
    clean = re.sub(r'\b(?:class|style|src|alt|href|width|height|id|data-\w+)=["\'][^"\']*["\']?\s*', '', clean, flags=re.IGNORECASE)

    # 4. Decode HTML entities
    clean = clean.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    clean = clean.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    clean = _HTML_ENTITY_RE.sub('', clean)

    # 5. Remove URLs/links
    clean = _URL_RE.sub('', clean)

    # 6. Clean up whitespace
    clean = re.sub(r'\n{4,}', '\n\n\n', clean)
    clean = re.sub(r'  +', ' ', clean)
    clean = '\n'.join(line.strip() for line in clean.split('\n'))
    clean = clean.strip()

    return clean


def validate_posts(
    linkedin_post: str,
    twitter_post: str,
    hashtags: list[str] = None,
) -> ValidationResult:
    """Validate LinkedIn and Twitter posts for quality, grammar, and language.

    Posts that contain HTML tags, URLs, or non-English text are immediately rejected.
    """
    result = ValidationResult()
    hashtags = hashtags or []

    # === HARD REJECTIONS (make post invalid) ===

    # 1. Check for HTML tags (CRITICAL - instant rejection)
    for label, post in [("LinkedIn", linkedin_post), ("Twitter", twitter_post)]:
        if post and _HTML_DETECT_RE.search(post):
            result.errors.append(f"{label} post contains raw HTML tags or attributes")
            result.quality_score -= 50
            result.is_valid = False

    # 2. Check for URLs/links (CRITICAL - instant rejection)
    for label, post in [("LinkedIn", linkedin_post), ("Twitter", twitter_post)]:
        if post and _URL_RE.search(post):
            result.errors.append(f"{label} post contains a URL/link (must be link-free)")
            result.quality_score -= 40
            result.is_valid = False

    # 3. Check for HTML entities (sign of unprocessed HTML)
    for label, post in [("LinkedIn", linkedin_post), ("Twitter", twitter_post)]:
        if post and _HTML_ENTITY_RE.search(post):
            result.errors.append(f"{label} post contains HTML entities")
            result.quality_score -= 30
            result.is_valid = False

    # 4. Check for conversational/error responses (AI didn't generate proper content)
    conversational_phrases = [
        "i cannot", "i apologize", "i'm sorry", "as an ai",
        "i don't have", "i can't", "unable to", "error occurred",
        "here is", "here's a", "sure, i'll", "certainly!", "of course!",
    ]
    for phrase in conversational_phrases:
        if phrase in linkedin_post.lower() or phrase in twitter_post.lower():
            result.errors.append(f"Posts contain AI conversational response: '{phrase}'")
            result.quality_score -= 50
            result.is_valid = False
            break

    # 5. Check for section labels (AI framework headings that should be internal only)
    section_labels = [
        r'\bHook:', r'\bContext:', r'\bInsight:', r'\bImpact:',
        r'\bAction:', r'\bEngagement:', r'\bCTA:',
        r'\[Write\b', r'\[Insert\b', r'\[Add\b', r'\[Your\b',
    ]
    for pattern in section_labels:
        if linkedin_post and re.search(pattern, linkedin_post, re.IGNORECASE):
            result.errors.append(f"LinkedIn post contains framework label: {pattern}")
            result.quality_score -= 30
            result.is_valid = False
            break

    # 6. Check for gibberish / broken text
    for label, post in [("LinkedIn", linkedin_post), ("Twitter", twitter_post)]:
        if post and _is_gibberish(post):
            result.errors.append(f"{label} post contains gibberish or broken text")
            result.quality_score -= 30
            result.is_valid = False

    # 7. LANGUAGE CHECK - ensure posts are English only
    for label, post in [("LinkedIn", linkedin_post), ("Twitter", twitter_post)]:
        if post:
            lang_result = _check_english(post)
            if not lang_result["is_english"]:
                result.errors.append(f"{label} post contains non-English text: {lang_result['reason']}")
                result.quality_score -= 40
                result.is_valid = False

    # === LENGTH CHECKS ===

    # 8. Check LinkedIn post exists and meets minimum length
    if not linkedin_post or len(linkedin_post.strip()) < 50:
        result.errors.append(f"LinkedIn post too short ({len(linkedin_post) if linkedin_post else 0} chars)")
        result.quality_score -= 30
        result.is_valid = False

    linkedin_words = len(linkedin_post.split()) if linkedin_post else 0
    if linkedin_words < 50:
        result.errors.append(f"LinkedIn post too few words: {linkedin_words} (minimum 50)")
        result.quality_score -= 20
        result.is_valid = False
    elif linkedin_words > 500:
        result.warnings.append(f"LinkedIn post is long: {linkedin_words} words")
        result.quality_score -= 5

    # 9. Check Twitter post length
    if not twitter_post or len(twitter_post.strip()) < 20:
        result.errors.append(f"Twitter post too short ({len(twitter_post) if twitter_post else 0} chars)")
        result.quality_score -= 30
        result.is_valid = False
    if twitter_post and len(twitter_post) > 280:
        result.errors.append(f"Twitter post too long: {len(twitter_post)} chars (max 280)")
        result.quality_score -= 20
        result.is_valid = False

    # === QUALITY CHECKS (warnings, reduce score but don't reject) ===

    # 10. Check for hashtags
    if linkedin_post and "#" not in linkedin_post:
        result.warnings.append("LinkedIn post missing hashtags")
        result.quality_score -= 5
    if twitter_post and "#" not in twitter_post:
        result.warnings.append("Twitter post missing hashtags")
        result.quality_score -= 5

    # 11. Check for emojis
    has_emoji = bool(re.search(r'[\U0001F300-\U0001F9FF]', linkedin_post)) if linkedin_post else False
    if not has_emoji and linkedin_post:
        result.warnings.append("LinkedIn post could use emojis for engagement")
        result.quality_score -= 3

    # 12. GRAMMAR CHECK
    if linkedin_post:
        grammar_issues = _check_grammar(linkedin_post)
        for issue in grammar_issues:
            result.warnings.append(f"Grammar: {issue}")
        result.quality_score -= min(len(grammar_issues) * 3, 15)

    if twitter_post:
        grammar_issues = _check_grammar(twitter_post)
        for issue in grammar_issues:
            result.warnings.append(f"Grammar (Twitter): {issue}")
        result.quality_score -= min(len(grammar_issues) * 3, 10)

    # Ensure score doesn't go below 0
    result.quality_score = max(0.0, result.quality_score)

    if result.is_valid and result.quality_score >= 70:
        logger.info(f"Posts validated: score={result.quality_score}")
    else:
        logger.warning(
            f"Validation issues: valid={result.is_valid}, score={result.quality_score}, "
            f"errors={result.errors}, warnings={result.warnings}"
        )

    return result


def _check_english(text: str) -> dict:
    """Check if text is in English by detecting non-Latin script characters."""
    non_latin = re.compile(
        r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af'
        r'\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f\u0400-\u04ff]'
    )
    matches = non_latin.findall(text)
    if len(matches) > 3:
        return {"is_english": False, "reason": f"Found {len(matches)} non-Latin characters"}
    return {"is_english": True, "reason": ""}


def _check_grammar(text: str) -> list[str]:
    """Grammar and quality checks for generated posts."""
    issues = []

    # Strip hashtags and emojis for analysis
    clean = re.sub(r'#\w+', '', text)
    clean = re.sub(r'[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]', '', clean)

    # Check for repeated words (e.g. "the the", "is is")
    repeated = re.findall(r'\b(\w+)\s+\1\b', clean, re.IGNORECASE)
    if repeated:
        issues.append(f"Repeated words: {', '.join(set(repeated)[:3])}")

    # Check for very long sentences (>60 words without punctuation)
    sentences = re.split(r'[.!?]\s', clean)
    for sent in sentences:
        word_count = len(sent.split())
        if word_count > 60:
            issues.append(f"Very long sentence ({word_count} words)")
            break

    # Check for missing spaces after punctuation
    missing_space = re.findall(r'[.!?,][A-Z]', clean)
    if len(missing_space) > 2:
        issues.append("Missing spaces after punctuation")

    # Check for unclosed parentheses or brackets
    if clean.count('(') != clean.count(')'):
        issues.append("Unclosed parentheses")
    if clean.count('[') != clean.count(']'):
        issues.append("Unclosed brackets")

    # Check for excessive CAPS (more than 40% uppercase)
    alpha_chars = re.findall(r'[A-Za-z]', clean)
    if alpha_chars:
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if upper_ratio > 0.40:
            issues.append("Excessive ALL CAPS usage")

    # Check for broken encoding / mojibake patterns
    mojibake_patterns = [
        'Ã¢', 'â€™', 'â€"', 'â€œ', 'â€\x9d',
        'Ã©', 'Ã¨', 'Ã¼',
    ]
    for pattern in mojibake_patterns:
        if pattern in text:
            issues.append("Broken character encoding (mojibake)")
            break

    # Check for CSS/code artifacts
    code_artifacts = ['class=', 'style=', 'src=', 'alt=', 'href=', 'width=', 'height=']
    for artifact in code_artifacts:
        if artifact in text:
            issues.append(f"Contains code artifact: {artifact}")
            break

    return issues


def _is_gibberish(text: str) -> bool:
    """Detect if text is gibberish or badly broken content."""
    # Check for high ratio of non-printable characters
    printable = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
    if len(text) > 0 and printable / len(text) < 0.85:
        return True

    # Check for excessive consecutive consonants (sign of broken text)
    if re.search(r'[bcdfghjklmnpqrstvwxyz]{8,}', text, re.IGNORECASE):
        return True

    # Check if text has very few real words
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text)
    if len(text) > 100 and len(words) < 5:
        return True

    # Check for repeated phrases (sign of AI loop)
    sentences = [s.strip() for s in re.split(r'[.!?\n]', text) if len(s.strip()) > 20]
    if len(sentences) > 3:
        unique = set(sentences)
        if len(unique) < len(sentences) * 0.5:
            return True

    return False
