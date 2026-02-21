"""LinkedIn OAuth2 authorization flow - URL generation, code exchange, token refresh."""
import logging
import os
import urllib.parse
from datetime import datetime, timezone, timedelta
import requests

from app.config import get_settings
from app.sheets_db import SheetsDB

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_PROFILE_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_ORG_URL = "https://api.linkedin.com/rest/organizationAcls"


def get_authorization_url(project_id: str) -> str:
    """Generate LinkedIn OAuth2 authorization URL with all scopes."""
    settings = get_settings()

    scopes = (
        "openid profile email "
        "w_member_social "
        "w_organization_social r_organization_social "
        "rw_organization_admin r_organization_admin"
    )

    state = project_id

    params = {
        "response_type": "code",
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "redirect_uri": settings.linkedin_redirect_uri,
        "state": state,
        "scope": scopes,
    }

    return f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str, project_id: str, db: SheetsDB) -> dict:
    """Exchange authorization code for tokens. Auto-detects personal + org profiles."""
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
        expires_in = token_data.get("expires_in", 5184000)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # --- Auto-detect personal user ID ---
        user_id = _get_user_id(access_token)

        # --- Update personal profile ---
        personal_profile = db.get_profile_by_keys(project_id, "linkedin", "personal")
        if personal_profile:
            db.update_profile(personal_profile["id"], {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_expires_at": expires_at,
                "platform_user_id": user_id if user_id else personal_profile["platform_user_id"],
                "is_active": bool(user_id),
            })

        # --- Auto-detect organizations ---
        org_ids = _get_admin_organizations(access_token)

        org_profile = db.get_profile_by_keys(project_id, "linkedin", "organization")
        if org_profile and org_ids:
            db.update_profile(org_profile["id"], {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_expires_at": expires_at,
                "platform_user_id": org_ids[0],
                "is_active": True,
            })
        elif org_profile and not org_ids:
            db.update_profile(org_profile["id"], {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_expires_at": expires_at,
                "is_active": False,
            })

        # Save tokens as Vercel env vars for persistence across cold starts
        if settings.is_vercel:
            _save_tokens_to_env(project_id, access_token, refresh_token,
                                user_id, org_ids[0] if org_ids else "")

        return {
            "success": True,
            "user_id": user_id,
            "org_ids": org_ids,
            "expires_at": expires_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        return {"success": False, "error": str(e)}


def refresh_access_token(profile: dict, db: SheetsDB) -> bool:
    """Refresh an expired LinkedIn access token."""
    settings = get_settings()

    if not profile.get("refresh_token"):
        logger.warning(f"No refresh token for profile {profile['id']}")
        return False

    data = {
        "grant_type": "refresh_token",
        "refresh_token": profile["refresh_token"],
        "client_id": settings.LINKEDIN_CLIENT_ID,
        "client_secret": settings.LINKEDIN_CLIENT_SECRET,
    }

    try:
        resp = requests.post(LINKEDIN_TOKEN_URL, data=data, timeout=30)
        resp.raise_for_status()
        token_data = resp.json()

        updates = {
            "access_token": token_data.get("access_token", ""),
        }
        if token_data.get("refresh_token"):
            updates["refresh_token"] = token_data["refresh_token"]
        expires_in = token_data.get("expires_in", 5184000)
        updates["token_expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        db.update_profile(profile["id"], updates)
        logger.info(f"Token refreshed for profile {profile['id']}")
        return True

    except Exception as e:
        logger.error(f"Token refresh failed for profile {profile['id']}: {e}")
        return False


def ensure_valid_token(profile: dict, db: SheetsDB) -> bool:
    """Check if token is valid, refresh if expiring within 7 days."""
    if not profile.get("access_token"):
        return False

    if profile.get("token_expires_at"):
        expires_at = profile["token_expires_at"]
        if isinstance(expires_at, str):
            from app.sheets_db import _parse_dt
            expires_at = _parse_dt(expires_at)
        if expires_at:
            days_until_expiry = (expires_at - datetime.now(timezone.utc)).days
            if days_until_expiry < 7:
                return refresh_access_token(profile, db)

    return True


def load_tokens_from_env(project_id: str, db: SheetsDB):
    """Load LinkedIn tokens from environment variables into Sheets profiles.

    Called during seed/startup to restore tokens after Vercel cold starts.
    """
    prefix = f"LINKEDIN_{project_id.upper()}"
    access_token = os.environ.get(f"{prefix}_ACCESS_TOKEN", "")
    refresh_token = os.environ.get(f"{prefix}_REFRESH_TOKEN", "")
    user_id = os.environ.get(f"{prefix}_USER_ID", "")
    org_id = os.environ.get(f"{prefix}_ORG_ID", "")

    if not access_token:
        return

    logger.info(f"Loading LinkedIn tokens from env vars for {project_id}")

    # Update personal profile
    personal = db.get_profile_by_keys(project_id, "linkedin", "personal")
    if personal and user_id:
        db.update_profile(personal["id"], {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "platform_user_id": user_id,
            "is_active": True,
        })

    # Update org profile
    org = db.get_profile_by_keys(project_id, "linkedin", "organization")
    if org and org_id:
        db.update_profile(org["id"], {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "platform_user_id": org_id,
            "is_active": True,
        })


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


def _get_admin_organizations(access_token: str) -> list[str]:
    """Get organization IDs where the user is an admin."""
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": "202601",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        params = {"q": "roleAssignee", "role": "ADMINISTRATOR", "count": 10}
        resp = requests.get(LINKEDIN_ORG_URL, headers=headers, params=params, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            org_ids = []
            for elem in data.get("elements", []):
                org_urn = elem.get("organization", "")
                if org_urn:
                    org_id = org_urn.split(":")[-1]
                    org_ids.append(org_id)
            logger.info(f"Found {len(org_ids)} admin organizations")
            return org_ids
        else:
            logger.warning(f"Org lookup returned {resp.status_code}: {resp.text[:200]}")
            return []
    except Exception as e:
        logger.warning(f"Could not fetch organizations: {e}")
        return []


def _save_tokens_to_env(project_id: str, access_token: str, refresh_token: str,
                         user_id: str, org_id: str):
    """Save tokens as Vercel env vars via API for persistence across cold starts."""
    settings = get_settings()

    if not settings.VERCEL_TOKEN or not settings.VERCEL_PROJECT_ID:
        logger.info("VERCEL_TOKEN/VERCEL_PROJECT_ID not set - tokens saved to Sheets only")
        return

    prefix = f"LINKEDIN_{project_id.upper()}"
    env_vars = {
        f"{prefix}_ACCESS_TOKEN": access_token,
        f"{prefix}_REFRESH_TOKEN": refresh_token,
        f"{prefix}_USER_ID": user_id,
        f"{prefix}_ORG_ID": org_id,
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
            resp = requests.get(f"{api_base}?key={key}", headers=headers, timeout=15)
            existing = resp.json().get("envs", [])

            if existing:
                env_id = existing[0]["id"]
                requests.patch(
                    f"{api_base}/{env_id}",
                    headers=headers,
                    json={"value": value},
                    timeout=15,
                )
            else:
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
            logger.info(f"Saved Vercel env var: {key}")
        except Exception as e:
            logger.error(f"Failed to save Vercel env {key}: {e}")
