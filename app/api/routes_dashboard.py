"""Dashboard HTML page routes (Jinja2 rendered)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


def _get_templates():
    from app.main import templates
    return templates


@router.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request):
    """Main overview dashboard."""
    return _get_templates().TemplateResponse("dashboard.html", {"request": request})


@router.get("/executions", response_class=HTMLResponse)
def executions_page(request: Request):
    """Pipeline execution history."""
    return _get_templates().TemplateResponse("executions.html", {"request": request})


@router.get("/content", response_class=HTMLResponse)
def content_page(request: Request):
    """Generated posts viewer."""
    return _get_templates().TemplateResponse("content.html", {"request": request})


@router.get("/articles", response_class=HTMLResponse)
def articles_page(request: Request):
    """Article history with scores."""
    return _get_templates().TemplateResponse("articles.html", {"request": request})


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """Project settings editor."""
    return _get_templates().TemplateResponse("settings.html", {"request": request})


@router.get("/profiles", response_class=HTMLResponse)
def profiles_page(request: Request):
    """LinkedIn/Twitter profile manager."""
    return _get_templates().TemplateResponse("profiles.html", {"request": request})


@router.get("/metrics", response_class=HTMLResponse)
def metrics_page(request: Request):
    """Quality metrics and charts."""
    return _get_templates().TemplateResponse("metrics.html", {"request": request})
