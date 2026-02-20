"""Twitter/X API v2 integration using tweepy."""
import json
import logging
from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_credentials_from_db(project_id: str) -> dict:
    """Try to load Twitter credentials from the database profile."""
    try:
        from app.database import SessionLocal
        from app.models import Profile

        db = SessionLocal()
        try:
            profile = (
                db.query(Profile)
                .filter(
                    Profile.project_id == project_id,
                    Profile.platform == "twitter",
                    Profile.account_type == "personal",
                    Profile.is_active == True,
                )
                .first()
            )
            if profile and profile.extra_config:
                config = json.loads(profile.extra_config)
                if all(config.get(k) for k in ["api_key", "api_secret", "access_token", "access_secret"]):
                    return config
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Could not load Twitter creds from DB for {project_id}: {e}")
    return {}


def publish_to_twitter(tweet_content: str, project_id: str) -> dict:
    """Post a tweet using tweepy Client.

    Checks DB-stored credentials first, then falls back to environment variables.

    Returns: {"success": bool, "tweet_id": str, "error": str}
    """
    # Try DB credentials first
    db_creds = _get_credentials_from_db(project_id)
    if db_creds:
        api_key = db_creds["api_key"]
        api_secret = db_creds["api_secret"]
        access_token = db_creds["access_token"]
        access_secret = db_creds["access_secret"]
    else:
        # Fall back to environment variables
        settings = get_settings()
        prefix = project_id.upper()
        api_key = getattr(settings, f"TWITTER_{prefix}_API_KEY", "")
        api_secret = getattr(settings, f"TWITTER_{prefix}_API_SECRET", "")
        access_token = getattr(settings, f"TWITTER_{prefix}_ACCESS_TOKEN", "")
        access_secret = getattr(settings, f"TWITTER_{prefix}_ACCESS_SECRET", "")

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
