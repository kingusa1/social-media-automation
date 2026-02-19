"""Twitter/X API v2 integration using tweepy."""
import logging
from app.config import get_settings

logger = logging.getLogger(__name__)


def publish_to_twitter(tweet_content: str, project_id: str) -> dict:
    """Post a tweet using tweepy Client.

    Uses OAuth 1.0a credentials from environment variables per project.

    Returns: {"success": bool, "tweet_id": str, "error": str}
    """
    settings = get_settings()

    # Get project-specific Twitter credentials
    if project_id == "infiniteo":
        api_key = settings.TWITTER_INFINITEO_API_KEY
        api_secret = settings.TWITTER_INFINITEO_API_SECRET
        access_token = settings.TWITTER_INFINITEO_ACCESS_TOKEN
        access_secret = settings.TWITTER_INFINITEO_ACCESS_SECRET
    elif project_id == "yourops":
        api_key = settings.TWITTER_YOUROPS_API_KEY
        api_secret = settings.TWITTER_YOUROPS_API_SECRET
        access_token = settings.TWITTER_YOUROPS_ACCESS_TOKEN
        access_secret = settings.TWITTER_YOUROPS_ACCESS_SECRET
    else:
        return {"success": False, "tweet_id": "", "error": f"Unknown project: {project_id}"}

    if not all([api_key, api_secret, access_token, access_secret]):
        return {"success": False, "tweet_id": "", "error": "Twitter credentials not configured"}

    try:
        import tweepy

        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )

        # Ensure tweet is within character limit
        if len(tweet_content) > 280:
            tweet_content = tweet_content[:277] + "..."

        response = client.create_tweet(text=tweet_content)

        if response and response.data:
            tweet_id = str(response.data.get("id", ""))
            logger.info(f"Tweet posted successfully: {tweet_id}")
            return {"success": True, "tweet_id": tweet_id, "error": ""}
        else:
            return {"success": False, "tweet_id": "", "error": "No response data from Twitter"}

    except Exception as e:
        logger.error(f"Twitter post failed: {e}")
        return {"success": False, "tweet_id": "", "error": str(e)}
