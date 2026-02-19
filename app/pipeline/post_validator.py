"""Validate AI-generated social media posts for quality and brand compliance.

Faithfully replicates the n8n Quality Check - Validate Posts node logic.
"""
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
    """Validate LinkedIn and Twitter posts for quality."""
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
        result.quality_score -= 10

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
