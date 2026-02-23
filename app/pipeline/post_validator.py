"""Validate AI-generated social media posts for quality, grammar, and brand compliance."""
import logging
import re

logger = logging.getLogger(__name__)


class ValidationResult:
    def __init__(self):
        self.is_valid = True
        self.quality_score = 100.0
        self.errors: list[str] = []
        self.warnings: list[str] = []


def validate_posts(
    linkedin_post: str,
    twitter_post: str,
    hashtags: list[str] = None,
) -> ValidationResult:
    """Validate LinkedIn and Twitter posts for quality, grammar, and language."""
    result = ValidationResult()
    hashtags = hashtags or []

    # 1. Check for conversational/error responses (AI didn't generate proper content)
    conversational_phrases = [
        "i cannot", "i apologize", "i'm sorry", "as an ai",
        "i don't have", "i can't", "unable to", "error occurred",
    ]
    for phrase in conversational_phrases:
        if phrase in linkedin_post.lower() or phrase in twitter_post.lower():
            result.errors.append(f"Posts contain error/conversational response: '{phrase}'")
            result.quality_score -= 50
            result.is_valid = False
            break

    # 2. Check LinkedIn post exists and has minimum length
    if not linkedin_post or len(linkedin_post.strip()) < 50:
        result.errors.append(f"LinkedIn post too short ({len(linkedin_post)} chars, minimum 50)")
        result.quality_score -= 30
        result.is_valid = False

    # 3. Check Twitter post exists and has minimum length
    if not twitter_post or len(twitter_post.strip()) < 20:
        result.errors.append(f"Twitter post too short ({len(twitter_post)} chars, minimum 20)")
        result.quality_score -= 30
        result.is_valid = False

    # 4. Validate LinkedIn word count (100-500 words target)
    linkedin_words = len(linkedin_post.split()) if linkedin_post else 0
    if linkedin_words < 50:
        result.errors.append(f"LinkedIn post too short: {linkedin_words} words (minimum 50)")
        result.quality_score -= 20
        result.is_valid = False
    elif linkedin_words > 500:
        result.warnings.append(f"LinkedIn post is long: {linkedin_words} words (recommended max 500)")
        result.quality_score -= 5

    # 5. Validate Twitter post length
    if twitter_post and len(twitter_post) > 280:
        result.errors.append(f"Twitter post too long: {len(twitter_post)} chars (max 280)")
        result.quality_score -= 20
        result.is_valid = False

    # 6. Check for placeholder text
    placeholders = ["[insert", "[add", "[your", "placeholder", "example text", "lorem ipsum"]
    for placeholder in placeholders:
        if placeholder in linkedin_post.lower() or placeholder in twitter_post.lower():
            result.errors.append(f"Posts contain placeholder text: '{placeholder}'")
            result.quality_score -= 25
            result.is_valid = False

    # 7. Check for hashtags in LinkedIn post
    if linkedin_post and "#" not in linkedin_post:
        result.warnings.append("LinkedIn post missing hashtags")
        result.quality_score -= 5

    # 8. Check for hashtags in Twitter post
    if twitter_post and "#" not in twitter_post:
        result.warnings.append("Twitter post missing hashtags")
        result.quality_score -= 5

    # 9. Check for emojis (nice to have)
    has_emoji = bool(re.search(r"[\U0001F300-\U0001F9FF]", linkedin_post))
    if not has_emoji and linkedin_post:
        result.warnings.append("LinkedIn post may benefit from emojis")
        result.quality_score -= 3

    # 10. LANGUAGE CHECK - ensure posts are English only
    if linkedin_post:
        lang_result = _check_english(linkedin_post)
        if not lang_result["is_english"]:
            result.errors.append(f"LinkedIn post contains non-English text: {lang_result['reason']}")
            result.quality_score -= 40
            result.is_valid = False

    if twitter_post:
        lang_result = _check_english(twitter_post)
        if not lang_result["is_english"]:
            result.errors.append(f"Twitter post contains non-English text: {lang_result['reason']}")
            result.quality_score -= 40
            result.is_valid = False

    # 11. GRAMMAR CHECK - basic quality checks
    if linkedin_post:
        grammar_issues = _check_grammar(linkedin_post)
        if grammar_issues:
            for issue in grammar_issues:
                result.warnings.append(f"Grammar: {issue}")
            result.quality_score -= min(len(grammar_issues) * 3, 15)

    if twitter_post:
        grammar_issues = _check_grammar(twitter_post)
        if grammar_issues:
            for issue in grammar_issues:
                result.warnings.append(f"Grammar (Twitter): {issue}")
            result.quality_score -= min(len(grammar_issues) * 3, 10)

    # 12. Check for unwanted links/URLs (should not appear in posts)
    url_pattern = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
    if linkedin_post and url_pattern.search(linkedin_post):
        result.warnings.append("LinkedIn post contains a URL (should be link-free)")
        result.quality_score -= 10
    if twitter_post and url_pattern.search(twitter_post):
        result.warnings.append("Twitter post contains a URL (should be link-free)")
        result.quality_score -= 10

    # 13. Check for gibberish / broken text
    if linkedin_post and _is_gibberish(linkedin_post):
        result.errors.append("LinkedIn post appears to contain gibberish or broken text")
        result.quality_score -= 30
        result.is_valid = False

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
    # CJK, Arabic, Cyrillic, Devanagari, Thai, Korean, Japanese
    non_latin = re.compile(
        r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af'
        r'\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f\u0400-\u04ff]'
    )
    matches = non_latin.findall(text)
    if len(matches) > 3:
        return {"is_english": False, "reason": f"Found {len(matches)} non-Latin characters"}
    return {"is_english": True, "reason": ""}


def _check_grammar(text: str) -> list[str]:
    """Basic grammar and quality checks for generated posts.

    Returns a list of grammar issue descriptions.
    """
    issues = []

    # Strip hashtags and emojis for analysis
    clean = re.sub(r'#\w+', '', text)
    clean = re.sub(r'[\U0001F300-\U0001F9FF\u2600-\u26FF\u2700-\u27BF]', '', clean)

    # Check for repeated words (e.g. "the the", "is is")
    repeated = re.findall(r'\b(\w+)\s+\1\b', clean, re.IGNORECASE)
    if repeated:
        issues.append(f"Repeated words: {', '.join(set(repeated)[:3])}")

    # Check for very long sentences (>50 words without punctuation)
    sentences = re.split(r'[.!?]\s', clean)
    for sent in sentences:
        word_count = len(sent.split())
        if word_count > 60:
            issues.append(f"Very long sentence ({word_count} words) - may be hard to read")
            break

    # Check for missing spaces after punctuation
    missing_space = re.findall(r'[.!?,][A-Z]', clean)
    if len(missing_space) > 2:
        issues.append("Missing spaces after punctuation in multiple places")

    # Check for unclosed parentheses or brackets
    if clean.count('(') != clean.count(')'):
        issues.append("Unclosed parentheses")
    if clean.count('[') != clean.count(']'):
        issues.append("Unclosed brackets")

    # Check for excessive CAPS (more than 30% of alphabetic characters)
    alpha_chars = re.findall(r'[A-Za-z]', clean)
    if alpha_chars:
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if upper_ratio > 0.40:
            issues.append("Excessive use of ALL CAPS (may look spammy)")

    # Check for broken encoding / mojibake patterns
    mojibake_patterns = [
        r'Ã¢\u20ac', r'â€™', r'â€"', r'â€œ', r'â€\x9d',
        r'Ã©', r'Ã¨', r'Ã¼', r'\u00c3', r'\u00e2\u20ac',
    ]
    for pattern in mojibake_patterns:
        if pattern in text:
            issues.append("Broken character encoding detected (mojibake)")
            break

    return issues


def _is_gibberish(text: str) -> bool:
    """Detect if text is gibberish or badly broken content."""
    # Check for high ratio of special/non-printable characters
    printable = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
    if len(text) > 0 and printable / len(text) < 0.85:
        return True

    # Check for excessive consecutive consonants (sign of broken text)
    if re.search(r'[bcdfghjklmnpqrstvwxyz]{8,}', text, re.IGNORECASE):
        return True

    # Check if text has very few real words (less than 30% dictionary-like)
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text)
    if len(text) > 100 and len(words) < 5:
        return True

    return False
