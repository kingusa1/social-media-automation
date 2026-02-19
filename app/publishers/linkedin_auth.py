"""LinkedIn OAuth2 authorization flow - URL generation, code exchange, token refresh."""
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
import requests
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Profile

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_PROFILE_URL = "https://api.linkedin.com/v2/userinfo"


def get_authorization_url(project_id: str, account_type: str) -> str:
    """Generate LinkedIn OAuth2 authorization URL."""
    settings = get_settings()

    scopes = "openid profile email w_member_social"
    if account_type == "organization":
        scopes += " w_organization_social r_organization_social"

    state = f"{project_id}|{account_type}"

    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": settings.linkedin_redirect_uri,
        "state": state,
        "scope": scopes,
    }

    return f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str, project_id: str, account_type: str, db: Session) -> dict:
    """Exchange authorization code for access and refresh tokens."""
    settings = get_settings()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.linkedin_redirect_uri,
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "client_secret": settings.LINKEDIN_CLIENT_SECRET,
    }

    try:
        resp = requests.post(LINKEDIN_TOKEN_URL, data=data, timeout=30)
        resp.raise_for_status()
        token_data = resp.json()

        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 5184000)  # Default 60 days
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Get user profile to get the person ID
        user_id = ""
        if account_type == "personal":
            user_id = _get_user_id(access_token)

        # Update profile in DB
        profile = (
            db.query(Profile)
            .filter(
                Profile.project_id == project_id,
                Profile.platform == "linkedin",
                Profile.account_type == account_type,
            )
            .first()
        )

        if profile:
            profile.access_token = access_token
            profile.refresh_token = refresh_token
            profile.token_expires_at = expires_at
            if user_id:
                profile.platform_user_id = user_id
            profile.is_active = True
            db.commit()

        # If on Vercel, save tokens as env vars so they persist across deploys
        if settings.is_vercel and settings.VERCEL_TOKEN and settings.VERCEL_PROJECT_ID:
            _update_vercel_env(project_id, account_type, access_token, refresh_token, user_id)

        return {
            "success": True,
            "user_id": user_id,
            "expires_at": expires_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        return {"success": False, "error": str(e)}


def refresh_access_token(profile: Profile, db: Session) -> bool:
    """Refresh an expired LinkedIn access token."""
    settings = get_settings()

    if not profile.refresh_token:
        logger.warning(f"No refresh token for profile {profile.id}")
        return False

    data = {
        "grant_type": "refresh_token",
        "refresh_token": profile.refresh_token,
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "client_secret": settings.LINKEDIN_CLIENT_SECRET,
    }

    try:
        resp = requests.post(LINKEDIN_TOKEN_URL, data=data, timeout=30)
        resp.raise_for_status()
        token_data = resp.json()

        profile.access_token = token_data.get("access_token", "")
        if token_data.get("refresh_token"):
            profile.refresh_token = token_data["refresh_token"]
        expires_in = token_data.get("expires_in", 5184000)
        profile.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        db.commit()
        logger.info(f"Token refreshed for profile {profile.id}")
        return True

    except Exception as e:
        logger.error(f"Token refresh failed for profile {profile.id}: {e}")
        return False


def ensure_valid_token(profile: Profile, db: Session) -> bool:
    """Check if token is valid, refresh if expiring within 7 days."""
    if not profile.access_token:
        return False

    if profile.token_expires_at:
        days_until_expiry = (profile.token_expires_at - datetime.now(timezone.utc)).days
        if days_until_expiry < 7:
            return refresh_access_token(profile, db)

    return True


def _get_user_id(access_token: str) -> str:
    """Get the LinkedIn user's person ID using the userinfo endpoint."""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(LINKEDIN_PROFILE_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("sub", "")
    except Exception as e:
        logger.warning(f"Could not fetch user profile: {e}")
        return ""


def _update_vercel_env(project_id: str, account_type: str, access_token: str, refresh_token: str, user_id: str):
    """Update Vercel environment variables with LinkedIn tokens so they persist across deploys."""
    settings = get_settings()
    prefix = f"LINKEDIN_{project_id.upper()}_{account_type.upper()}"

    env_vars = {
        f"{prefix}_ACCESS_TOKEN": access_token,
        f"{prefix}_REFRESH_TOKEN": refresh_token,
        f"{prefix}_USER_ID": user_id,
    }

    headers = {
        "Authorization": f"Bearer {settings.VERCEL_TOKEN}",
        "Content-Type": "application/json",
    }

    api_base = f"https://api.vercel.com/v10/projects/{settings.VERCEL_PROJECT_ID}/env"

    for key, value in env_vars.items():
        if not value:
            continue
        try:
            # Check if env var already exists
            resp = requests.get(f"{api_base}?key={key}", headers=headers, timeout=15)
            existing = resp.json().get("envs", [])

            if existing:
                # Update existing
                env_id = existing[0]["id"]
                requests.patch(
                    f"{api_base}/{env_id}",
                    headers=headers,
                    json={"value": value},
                    timeout=15,
                )
                logger.info(f"Updated Vercel env var: {key}")
            else:
                # Create new
                requests.post(
                    api_base,
                    headers=headers,
                    json={
                        "key": key,
                        "value": value,
                        "type": "encrypted",
                        "target": ["production", "preview"],
                    },
                    timeout=15,
                )
                logger.info(f"Created Vercel env var: {key}")
        except Exception as e:
            logger.error(f"Failed to update Vercel env {key}: {e}")
