"""Generate social media posts using Pollinations AI (OpenAI-compatible API).

Uses the openai Python library pointed at the Pollinations gen API endpoint.
Primary model: chickytutor (Claude 3.5 Haiku), with fallbacks to other models.
Implements retry with exponential backoff for rate limiting.
"""
import logging
import time
from typing import Optional
from openai import OpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)

# Total time budget for AI generation (seconds)
AI_TOTAL_BUDGET = 120
# Per-model timeout for the API call
MODEL_TIMEOUT = 30.0
# Retry delays for 429 rate limit errors (seconds)
RETRY_DELAYS = [3, 6, 12]
# Minimum response length to accept (must contain both post delimiters)
MIN_RESPONSE_LENGTH = 100


class AIGeneratedContent:
    def __init__(self, raw_output: str, model_used: str):
        self.raw_output = raw_output
        self.model_used = model_used


def _validate_ai_response(response: str) -> bool:
    """Check that the AI response contains the expected delimited format with real content."""
    if not response or len(response) < MIN_RESPONSE_LENGTH:
        return False
    # Must contain at least one delimiter indicating structured output
    has_linkedin = "---LINKEDIN---" in response or "LINKEDIN:" in response
    has_twitter = "---TWITTER---" in response or "TWITTER:" in response
    if has_linkedin and has_twitter:
        return True
    # Fallback: accept if it's long enough to be a real post (parser handles heuristics)
    if len(response) > 200:
        return True
    return False


def generate_posts(
    article_title: str,
    article_url: str,
    article_description: str,
    article_content: str,
    brand_voice: str,
) -> Optional[AIGeneratedContent]:
    """Generate LinkedIn + Twitter posts using Pollinations AI.

    Strategy:
    1. Try primary model (chickytutor) with retries for 429 errors
    2. If primary fails with non-429 error, try fallback models in order
    3. Each model gets proper retry handling for rate limits
    4. Validates response contains expected delimited format
    """
    settings = get_settings()

    system_prompt = _build_system_prompt(brand_voice)
    user_prompt = _build_user_prompt(article_title, article_url, article_description, article_content)

    # Build model chain: primary + fallbacks
    models = [settings.POLLINATIONS_PRIMARY_MODEL] + settings.fallback_models
    start_time = time.time()

    logger.info(f"AI generation starting: models={models}, article='{article_title[:60]}'")

    for model_idx, model in enumerate(models):
        elapsed = time.time() - start_time
        if elapsed > AI_TOTAL_BUDGET:
            logger.warning(f"AI time budget exhausted after {elapsed:.0f}s, tried {model_idx} models")
            break

        logger.info(f"Trying model {model_idx + 1}/{len(models)}: {model}")

        # Try this model with retries for 429 errors
        for retry in range(len(RETRY_DELAYS) + 1):
            elapsed = time.time() - start_time
            if elapsed > AI_TOTAL_BUDGET:
                break

            try:
                response = _call_ai(system_prompt, user_prompt, model, settings)

                if _validate_ai_response(response):
                    logger.info(
                        f"AI generation succeeded: model={model}, "
                        f"chars={len(response)}, time={time.time() - start_time:.1f}s"
                    )
                    return AIGeneratedContent(raw_output=response, model_used=model)
                else:
                    logger.warning(
                        f"Model {model} returned invalid/insufficient content "
                        f"({len(response) if response else 0} chars)"
                    )
                    break  # Don't retry insufficient content, try next model

            except Exception as e:
                error_str = str(e)

                if "429" in error_str or "rate" in error_str.lower() or "queue" in error_str.lower():
                    # Rate limited - wait and retry same model
                    if retry < len(RETRY_DELAYS):
                        wait = RETRY_DELAYS[retry]
                        logger.info(f"Model {model} rate limited, waiting {wait}s (retry {retry + 1}/{len(RETRY_DELAYS)})")
                        time.sleep(wait)
                        continue
                    else:
                        logger.warning(f"Model {model} still rate limited after {len(RETRY_DELAYS)} retries")
                        break  # Move to next model

                elif "404" in error_str or "not found" in error_str.lower():
                    logger.warning(f"Model {model} not found, skipping")
                    break

                elif "401" in error_str or "auth" in error_str.lower():
                    logger.error(f"Auth error for model {model}: {error_str[:150]}")
                    break

                elif "timeout" in error_str.lower() or "timed out" in error_str.lower():
                    logger.warning(f"Model {model} timed out after {MODEL_TIMEOUT}s")
                    break  # Move to next model

                else:
                    logger.warning(f"Model {model} error: {error_str[:150]}")
                    break

    total_time = time.time() - start_time
    logger.error(f"All {len(models)} AI models failed after {total_time:.1f}s")
    return None


def _build_system_prompt(brand_voice: str) -> str:
    """Build the full system prompt including brand voice and output format instructions."""
    return f"""{brand_voice}

=== CRITICAL RULES ===

1. Write NATURAL, flowing posts. NEVER include section labels like "Hook:", "Context:", "Insight:", "Impact:", "Action:", "Engagement:" in the output. These are internal guidelines ONLY.
2. The LinkedIn post should read like a real person breaking exciting news - bold, energetic, thought-provoking.
3. Use line breaks between paragraphs for readability.
4. Use emojis strategically to add energy (rocket, fire, brain, lightning bolt, pointing down, etc).
5. Hashtags go at the very end on their own line, using # format (e.g. #AI #Automation).
6. NEVER include article links or URLs in the LinkedIn post. NO links at all.
7. NEVER include article links or URLs in the Twitter post. NO links at all.

=== LINKEDIN POST STYLE ===

Write like you are BREAKING exciting news to your audience. The post should feel like a newsletter update that:
- Opens with a bold emoji-powered headline about the news
- Explains the breakthrough/development with excitement and specific numbers/facts
- Uses bullet points with emoji bullets to highlight key details
- Includes a "What this solves" or "The implications are MASSIVE" section showing real-world impact
- Shows how the company (from brand voice) helps with this
- Ends with a call-to-action question asking readers to comment + pointing down emoji
- Uses CAPS for emphasis on key words (e.g. "FOREVER", "MASSIVE", "GAME-CHANGER")
- Feels like a CEO who is genuinely excited about this news

=== OUTPUT FORMAT ===

You MUST output in this exact format:

---LINKEDIN---
[Write an energetic, news-breaking LinkedIn post - 200-400 words. NO links. NO URLs. Use emojis, bullet points, bold statements.]
---TWITTER---
[Write your Twitter/X post here - under 250 characters. NO links. NO URLs. Punchy and exciting.]
---END---

=== DO NOT SKIP EITHER POST ==="""


def _build_user_prompt(
    title: str,
    _url: str,
    description: str,
    content: str,
) -> str:
    """Build the user prompt with article details."""
    return f"""Create engaging social media posts for this news article:

Title: {title}
Description: {description[:500] if description else 'N/A'}
Article Content: {content[:2500] if content else 'N/A'}

Create 2 powerful, news-breaking social posts that will drive engagement and establish thought leadership.

IMPORTANT: Do NOT include any links or URLs in either post. Write the posts as pure content with no links."""


def _call_ai(
    system_prompt: str,
    user_prompt: str,
    model: str,
    settings,
) -> Optional[str]:
    """Make the actual API call to Pollinations AI with timeout."""
    client = OpenAI(
        api_key=settings.POLLINATIONS_API_KEY or "dummy",
        base_url=settings.POLLINATIONS_API_BASE,
        timeout=MODEL_TIMEOUT,
        max_retries=0,  # We handle retries ourselves
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1500,
        temperature=0.7,
    )

    if response.choices and response.choices[0].message.content:
        content = response.choices[0].message.content.strip()
        if content:
            return content
    logger.warning(f"Model {model} returned empty response")
    return None
