"""LinkedIn OAuth2 callback routes."""
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.publishers.linkedin_auth import get_authorization_url, exchange_code_for_token

router = APIRouter()


@router.get("/linkedin/start")
def linkedin_auth_start(project_id: str, account_type: str = "personal"):
    """Redirect to LinkedIn OAuth2 authorization page."""
    settings = get_settings()
    if not settings.LINKEDIN_CLIENT_ID or not settings.LINKEDIN_CLIENT_SECRET:
        msg = quote("LinkedIn not configured. Add LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in Vercel env vars. Create an app at linkedin.com/developers/apps")
        return RedirectResponse(url=f"/profiles?error={msg}")
    auth_url = get_authorization_url(project_id, account_type)
    return RedirectResponse(url=auth_url)


@router.get("/linkedin/callback")
def linkedin_auth_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    """Handle LinkedIn OAuth2 callback - exchange code for tokens."""
    # Parse state to get project_id and account_type
    parts = state.split("|")
    project_id = parts[0] if parts else ""
    account_type = parts[1] if len(parts) > 1 else "personal"

    if not project_id:
        return RedirectResponse(url="/profiles?error=invalid_state")

    result = exchange_code_for_token(code, project_id, account_type, db)

    if result.get("success"):
        return RedirectResponse(url=f"/profiles?success=linkedin_connected&project={project_id}")
    else:
        error = result.get("error", "unknown")
        return RedirectResponse(url=f"/profiles?error={error}")
