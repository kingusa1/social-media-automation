# Social Media Automation System

Automated content pipeline for **Infiniteo** and **YourOps** that fetches industry news, generates AI-powered LinkedIn and Twitter posts, and publishes them on schedule.

## What It Does

1. **Fetches RSS feeds** - 7 feeds per project (sales/AI for Infiniteo, DevOps/SRE for YourOps)
2. **Deduplicates** articles against the database
3. **Scores** articles for brand relevance using keyword weights and combo bonuses
4. **Extracts** full article content from the best-scoring article
5. **Generates** LinkedIn + Twitter posts using Pollinations AI with brand-specific voice
6. **Validates** post quality (conversational tone, hashtags, length, no placeholders)
7. **Publishes** to LinkedIn (personal + organization) and Twitter
8. **Logs** everything to the operations dashboard

## Dashboard

Dark-themed Bootstrap 5 web dashboard with:
- Project overview cards with run status
- Pipeline execution history with step-by-step logs
- Generated post viewer with copy-to-clipboard
- Article history with relevance scores
- Metrics with charts (run status, top sources)
- Profile manager for LinkedIn OAuth and Twitter credentials
- Project settings editor (RSS feeds, hashtags, scoring weights)

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy
- **AI**: Pollinations AI (OpenAI-compatible API) with model fallback chain
- **Database**: PostgreSQL (production) / SQLite (local development)
- **Frontend**: Jinja2 + Bootstrap 5 (server-rendered)
- **Scheduling**: Vercel Cron Jobs (production) / APScheduler (local)
- **Deployment**: Vercel

## Quick Start (Local)

```bash
# Clone the repo
git clone https://github.com/kingusa1/social-media-automation.git
cd social-media-automation

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys

# Run the server
python run.py
```

Open http://localhost:8000 to access the dashboard.

## Deploy to Vercel

### 1. Push to GitHub
The repo is already configured for Vercel with `vercel.json` and `api/index.py`.

### 2. Create Vercel Project
- Import the GitHub repo at https://vercel.com/new
- Vercel will auto-detect the Python configuration

### 3. Set Up Database
Create a **Vercel Postgres** (Neon) database from your Vercel project dashboard, or use any PostgreSQL provider.

### 4. Configure Environment Variables
Set these in Vercel project settings > Environment Variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `APP_URL` | Yes | Your Vercel domain (e.g. `https://your-app.vercel.app`) |
| `SECRET_KEY` | Yes | Random string for session security |
| `CRON_SECRET` | Yes | Random string to protect cron endpoints |
| `POLLINATIONS_API_KEY` | No | Pollinations API key (works without for free models) |
| `LINKEDIN_CLIENT_ID` | Yes | From LinkedIn Developer App |
| `LINKEDIN_CLIENT_SECRET` | Yes | From LinkedIn Developer App |
| `VERCEL_TOKEN` | Optional | Vercel API token (to auto-save LinkedIn tokens as env vars) |
| `VERCEL_PROJECT_ID` | Optional | Vercel project ID (paired with VERCEL_TOKEN) |

### 5. Set Up LinkedIn App
1. Go to https://www.linkedin.com/developers/apps
2. Create an app, add products: **Share on LinkedIn** + **Manage Company Pages**
3. Add redirect URL: `https://your-app.vercel.app/auth/linkedin/callback`
4. Copy Client ID and Client Secret to Vercel env vars

### 6. Cron Jobs
Vercel Cron Jobs are pre-configured in `vercel.json`:
- **Infiniteo**: Daily at 2:00 PM UTC
- **YourOps**: Weekdays at 10:00 AM UTC

> Note: Cron Jobs require Vercel Pro plan. On free plan, use https://cron-job.org to hit `/api/cron/run/infiniteo` and `/api/cron/run/yourops` on schedule.

## Projects

### Infiniteo
- **Focus**: Business Process Automation, AI, Sales Technology
- **RSS Sources**: Salesforce Blog, Sales Hacker, Axios, The Verge AI, Wired AI, ZDNet AI, TechCrunch AI
- **Schedule**: Daily at 2:00 PM UTC

### YourOps
- **Focus**: IT Operations, DevOps, SRE, Cloud Infrastructure
- **RSS Sources**: DevOps.com, The New Stack, Google SRE, AWS DevOps, Kubernetes, HashiCorp, InfoQ
- **Schedule**: Weekdays at 10:00 AM UTC

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/overview` | Dashboard overview for all projects |
| GET | `/api/runs` | List pipeline runs |
| POST | `/api/runs/trigger` | Manually trigger a pipeline |
| GET | `/api/posts` | List generated posts |
| GET | `/api/articles` | List fetched articles |
| GET | `/api/projects` | List/manage projects |
| GET | `/api/profiles` | List/manage social media profiles |
| GET | `/api/metrics` | Aggregated metrics |
| GET | `/api/cron/run/{project_id}` | Cron trigger endpoint |
| GET | `/auth/linkedin/start` | Start LinkedIn OAuth flow |

## Architecture

```
app/
  main.py              # FastAPI app + lifespan
  config.py            # Pydantic settings from .env
  database.py          # SQLAlchemy engine (SQLite/PostgreSQL)
  models.py            # ORM models (Project, Article, PipelineRun, etc.)
  schemas.py           # Pydantic request/response schemas
  api/
    routes_api.py      # REST API endpoints
    routes_auth.py     # LinkedIn OAuth callbacks
    routes_cron.py     # Vercel cron trigger endpoints
    routes_dashboard.py # HTML page routes
  pipeline/
    orchestrator.py    # 16-step pipeline runner
    rss_fetcher.py     # Parallel RSS fetching
    url_resolver.py    # Google News URL resolution
    deduplicator.py    # DB-backed deduplication
    scorer.py          # Relevance scoring with keyword weights
    content_extractor.py # HTML content extraction
    ai_generator.py    # Pollinations AI post generation
    post_parser.py     # AI output parsing
    post_validator.py  # Quality validation
    fallback_templates.py # Template-based fallback posts
  publishers/
    linkedin_auth.py   # OAuth2 flow + Vercel env sync
    linkedin_publisher.py # LinkedIn Posts API
    twitter_publisher.py  # Twitter/X API
  scheduler/
    scheduler.py       # APScheduler (local development only)
  templates/           # Jinja2 HTML templates
  static/              # CSS + JS assets
```
