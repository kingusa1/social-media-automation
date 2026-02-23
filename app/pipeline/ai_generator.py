"""Generate social media posts using Pollinations AI (OpenAI-compatible API).

Uses the openai Python library pointed at the Pollinations endpoint.
Implements model fallback chain: chickytutor -> openai -> mistral -> gemini.
"""
import logging
from typing import Optional
from openai import OpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)


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
    """Generate LinkedIn + Twitter posts using Pollinations AI with fallback chain."""
    settings = get_settings()

    system_prompt = _build_system_prompt(brand_voice)
    user_prompt = _build_user_prompt(article_title, article_url, article_description, article_content)

    # Build model chain: primary + fallbacks
    models = [settings.POLLINATIONS_PRIMARY_MODEL] + settings.fallback_models

    for model in models:
        try:
            response = _call_ai(system_prompt, user_prompt, model, settings)
            if response and len(response) > 50:
                logger.info(f"AI generation succeeded with model: {model}")
                return AIGeneratedContent(raw_output=response, model_used=model)
            else:
                logger.warning(f"Model {model} returned insufficient content")
        except Exception as e:
            logger.warning(f"Model {model} failed: {e}")

    logger.error("All AI models failed to generate content")
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
        timeout=30.0,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=1000,
        temperature=0.7,
    )

    if response.choices and response.choices[0].message.content:
        return response.choices[0].message.content.strip()
    return None
