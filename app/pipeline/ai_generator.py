"""Generate social media posts using Pollinations AI (OpenAI-compatible API).

Uses the openai Python library pointed at the Pollinations gen API endpoint.
Primary model: openai (GPT-5 Mini), with fallbacks to mistral, gemini, etc.
Implements retry with exponential backoff for rate limiting.
"""
import logging
import time
from typing import Optional
from openai import OpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)

# Total time budget for AI generation (seconds)
AI_TOTAL_BUDGET = 90
# Per-model timeout for the API call
MODEL_TIMEOUT = 25.0
# Retry delays for 429 rate limit errors (seconds)
RETRY_DELAYS = [3, 6, 10]


class AIGeneratedContent:
    def __init__(self, raw_output: str, model_used: str):
        self.raw_output = raw_output
        self.model_used = model_used


def generate_posts(
    article_title: str,
    article_url: str,
    article_description: str,
    article_content: str,
    brand_voice: str,
) -> Optional[AIGeneratedContent]:
    """Generate LinkedIn + Twitter posts using Pollinations AI.

    Strategy:
    1. Try primary model (openai/GPT-5 Mini) with retries for 429 errors
    2. If primary fails, try fallback models (mistral, gemini, etc.)
    3. Skip models that return 400/402/404 immediately
    """
    settings = get_settings()

    system_prompt = _build_system_prompt(brand_voice)
    user_prompt = _build_user_prompt(article_title, article_url, article_description, article_content)

    # Build model chain: primary + fallbacks
    models = [settings.POLLINATIONS_PRIMARY_MODEL] + settings.fallback_models
    start_time = time.time()

    for model_idx, model in enumerate(models):
        elapsed = time.time() - start_time
        if elapsed > AI_TOTAL_BUDGET:
            logger.warning(f"AI time budget exhausted after {elapsed:.0f}s, tried {model_idx} models")
            break

        # Try this model with retries for 429 errors
        for retry in range(len(RETRY_DELAYS) + 1):
            elapsed = time.time() - start_time
            if elapsed > AI_TOTAL_BUDGET:
                break

            try:
                response = _call_ai(system_prompt, user_prompt, model, settings)
                if response and len(response) > 50:
                    logger.info(f"AI generation succeeded: model={model}, time={time.time() - start_time:.1f}s")
                    return AIGeneratedContent(raw_output=response, model_used=model)
                else:
                    logger.warning(f"Model {model} returned insufficient content ({len(response) if response else 0} chars)")
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

                elif "400" in error_str or "invalid" in error_str.lower() or "BAD_REQUEST" in error_str:
                    logger.warning(f"Model {model} invalid/bad request, skipping: {error_str[:100]}")
                    break

                elif "401" in error_str or "402" in error_str or "auth" in error_str.lower() or "PAYMENT_REQUIRED" in error_str:
                    logger.error(f"Auth/payment error for model {model}: {error_str[:100]}")
                    break

                else:
                    # Other error - log and try next model
                    logger.warning(f"Model {model} error: {error_str[:100]}")
                    break

    total_time = time.time() - start_time
    logger.error(f"All AI models failed after {total_time:.1f}s")
    return None


def _build_system_prompt(brand_voice: str) -> str:
    """Build the full system prompt including brand voice and output format instructions."""
    return f"""{brand_voice}

=== ABSOLUTE RULES (VIOLATION = REJECTION) ===

1. NEVER include ANY URLs or links. Zero. None. Not even partial URLs.
2. NEVER include section labels like "Hook:", "Context:", "Insight:" etc.
3. NEVER include HTML tags, markdown formatting, or code artifacts.
4. NEVER start with "I" or write in first-person singular.
5. NEVER use generic filler phrases like "In today's rapidly evolving landscape".

=== LINKEDIN POST REQUIREMENTS ===

Write a HIGH-ENGAGEMENT LinkedIn post that stops the scroll. Study these patterns from viral posts:

OPENING (first 2 lines = make or break):
- Start with a bold, specific claim or surprising stat from the article
- Use ONE powerful emoji at the start, then a statement that creates curiosity
- Example: "🔥 Companies using AI automation are closing deals 47% faster. Here's what changed."
- The first line must make someone STOP scrolling and click "see more"

BODY (the value):
- Share the KEY insight from the article with specific numbers/data
- Use short paragraphs (1-3 sentences max) with blank lines between them
- Include 3-4 bullet points with emoji bullets showing concrete takeaways
- Each bullet should be actionable or contain a surprising fact
- Weave in how the company helps with this naturally (not forced)

CLOSING (drive engagement):
- End with a specific, thought-provoking question (not generic "What do you think?")
- Add 5-8 relevant hashtags on the final line
- Use a pointing-down emoji before the CTA question

TONE: Write like a respected industry insider sharing exclusive intelligence.
Confident but not arrogant. Data-driven but not dry. Bold but credible.

LENGTH: 200-350 words. Every word must earn its place.

=== TWITTER/X POST REQUIREMENTS ===

- Under 250 characters total (STRICT limit)
- Lead with the most surprising fact or boldest claim
- One or two relevant emojis
- 2-3 hashtags
- Must stand alone without context - punchy and shareable

=== OUTPUT FORMAT (EXACT) ===

---LINKEDIN---
[Your LinkedIn post here]
---TWITTER---
[Your Twitter post here]
---END---"""


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
    # Strip whitespace from settings to prevent trailing newline issues
    api_key = (settings.POLLINATIONS_API_KEY or "dummy").strip()
    api_base = settings.POLLINATIONS_API_BASE.strip()
    model = model.strip()

    client = OpenAI(
        api_key=api_key,
        base_url=api_base,
        timeout=MODEL_TIMEOUT,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1200,
        temperature=0.7,
    )

    if response.choices and response.choices[0].message.content:
        return response.choices[0].message.content.strip()
    return None
