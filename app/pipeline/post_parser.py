"""Parse AI-generated output into structured LinkedIn and Twitter posts.

Handles the ---LINKEDIN--- / ---TWITTER--- / ---END--- delimited format,
with heuristic fallbacks if the AI doesn't follow the format exactly.
Faithfully replicates the n8n 35_Generate_Insurance_Content parsing logic.
"""
import logging
import re

logger = logging.getLogger(__name__)


class ParsedPosts:
    def __init__(self, linkedin_post: str, twitter_post: str):
        self.linkedin_post = linkedin_post
        self.twitter_post = twitter_post


def parse_ai_output(raw_output: str) -> ParsedPosts:
    """Parse AI output into separate LinkedIn and Twitter posts."""
    if not raw_output:
        return ParsedPosts("", "")

    linkedin_post = ""
    twitter_post = ""

    # Strategy 1: Look for ---LINKEDIN--- / ---TWITTER--- markers
    linkedin_match = re.search(
        r"---LINKEDIN---\s*(.+?)\s*---TWITTER---",
        raw_output,
        re.DOTALL,
    )
    twitter_match = re.search(
        r"---TWITTER---\s*(.+?)\s*(?:---END---|$)",
        raw_output,
        re.DOTALL,
    )

    if linkedin_match:
        linkedin_post = linkedin_match.group(1).strip()
    if twitter_match:
        twitter_post = twitter_match.group(1).strip()

    # Strategy 2: Try LINKEDIN: / TWITTER: labels (n8n format)
    if not linkedin_post or not twitter_post:
        li_match = re.search(r"LINKEDIN:\s*(.+?)(?=TWITTER:|$)", raw_output, re.DOTALL)
        tw_match = re.search(r"TWITTER:\s*(.+?)$", raw_output, re.DOTALL)
        if li_match and not linkedin_post:
            linkedin_post = li_match.group(1).strip()
        if tw_match and not twitter_post:
            twitter_post = tw_match.group(1).strip()

    # Strategy 3: Try **LinkedIn** / **Twitter** markdown headers
    if not linkedin_post or not twitter_post:
        li_match = re.search(
            r"\*\*LinkedIn[^*]*\*\*[:\s]*(.+?)(?=\*\*Twitter|\*\*X\b|$)",
            raw_output,
            re.DOTALL | re.IGNORECASE,
        )
        tw_match = re.search(
            r"\*\*(?:Twitter|X)[^*]*\*\*[:\s]*(.+?)$",
            raw_output,
            re.DOTALL | re.IGNORECASE,
        )
        if li_match and not linkedin_post:
            linkedin_post = li_match.group(1).strip()
        if tw_match and not twitter_post:
            twitter_post = tw_match.group(1).strip()

    # Strategy 4: If we have content but couldn't parse it, use heuristics
    if not linkedin_post and not twitter_post and raw_output:
        # Split roughly in half - longer part is LinkedIn, shorter is Twitter
        paragraphs = [p.strip() for p in raw_output.split("\n\n") if p.strip()]
        if len(paragraphs) >= 2:
            # Last short paragraph might be the tweet
            last = paragraphs[-1]
            if len(last) < 300:
                twitter_post = last[:280]
                linkedin_post = "\n\n".join(paragraphs[:-1])
            else:
                linkedin_post = raw_output
                twitter_post = raw_output[:280]
        else:
            linkedin_post = raw_output
            twitter_post = raw_output[:280]

    # Clean up
    linkedin_post = _clean_post(linkedin_post)
    twitter_post = _clean_post(twitter_post)

    # Ensure Twitter post is within limit
    if len(twitter_post) > 280:
        # Try to cut at a sentence boundary
        cut = twitter_post[:277].rfind(". ")
        if cut > 200:
            twitter_post = twitter_post[: cut + 1]
        else:
            twitter_post = twitter_post[:277] + "..."

    logger.info(
        f"Parsed posts - LinkedIn: {len(linkedin_post)} chars, "
        f"Twitter: {len(twitter_post)} chars"
    )
    return ParsedPosts(linkedin_post, twitter_post)


def _clean_post(text: str) -> str:
    """Clean up a post by removing markdown artifacts and excess whitespace."""
    if not text:
        return ""
    # Remove markdown bold/italic markers
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    # Remove leading/trailing quotes
    text = text.strip('"\'')
    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
