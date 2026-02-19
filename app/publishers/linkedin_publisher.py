"""LinkedIn Posts API integration for personal and organization accounts."""
import logging
import requests
from app.models import Profile

logger = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com"


def publish_to_linkedin(post_content: str, profile: Profile) -> dict:
    """Post content to LinkedIn using the Posts API.

    Supports both personal (urn:li:person:XXX) and organization (urn:li:organization:XXX) accounts.

    Returns: {"success": bool, "post_id": str, "error": str}
    """
    if not profile.access_token:
        return {"success": False, "post_id": "", "error": "No access token configured"}

    if not profile.platform_user_id:
        return {"success": False, "post_id": "", "error": "No platform user ID configured"}

    # Build the author URN
    if profile.account_type == "organization":
        author = f"urn:li:organization:{profile.platform_user_id}"
    else:
        author = f"urn:li:person:{profile.platform_user_id}"

    headers = {
        "Authorization": f"Bearer {profile.access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": "202401",
    }

    payload = {
        "author": author,
        "commentary": post_content,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    for attempt in range(2):
        try:
            resp = requests.post(
                f"{LINKEDIN_API_BASE}/rest/posts",
                headers=headers,
                json=payload,
                timeout=30,
            )

            if resp.status_code in (200, 201):
                # LinkedIn returns the post URN in the x-restli-id header
                post_id = resp.headers.get("x-restli-id", "")
                logger.info(f"LinkedIn post successful: {post_id}")
                return {"success": True, "post_id": post_id, "error": ""}

            elif resp.status_code == 429:
                # Rate limited - wait and retry
                if attempt == 0:
                    import time
                    time.sleep(5)
                    continue
                return {"success": False, "post_id": "", "error": "Rate limited by LinkedIn"}

            elif resp.status_code == 401:
                return {"success": False, "post_id": "", "error": "Access token expired or invalid"}

            else:
                error_body = resp.text[:500]
                logger.error(f"LinkedIn API error {resp.status_code}: {error_body}")
                return {"success": False, "post_id": "", "error": f"API error {resp.status_code}: {error_body}"}

        except requests.exceptions.Timeout:
            if attempt == 0:
                continue
            return {"success": False, "post_id": "", "error": "Request timeout"}
        except Exception as e:
            return {"success": False, "post_id": "", "error": str(e)}

    return {"success": False, "post_id": "", "error": "Max retries exceeded"}
