"""Application configuration loaded from environment variables."""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

_project_root = os.path.dirname(os.path.dirname(__file__))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(_project_root, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    SECRET_KEY: str = "change-me-to-a-random-string"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Vercel / deployment
    APP_URL: str = "http://localhost:8000"
    CRON_SECRET: str = ""
    VERCEL: str = ""  # Set automatically by Vercel to "1"

    # Google Sheets (replaces PostgreSQL/SQLite)
    GOOGLE_SHEETS_CREDENTIALS_B64: str = ""
    GOOGLE_SHEETS_SPREADSHEET_ID: str = ""

    # Pollinations AI
    POLLINATIONS_API_KEY: str = ""
    POLLINATIONS_API_BASE: str = "https://text.pollinations.ai/openai"
    POLLINATIONS_PRIMARY_MODEL: str = "openai"
    POLLINATIONS_FALLBACK_MODELS: str = "openai-fast,mistral,gemini,deepseek,openai-large,gemini-fast,grok,kimi,nova-fast,glm,minimax,qwen-coder,claude-fast,claude,chickytutor"

    # LinkedIn OAuth2
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: str = ""

    # Twitter/X - Infiniteo
    TWITTER_INFINITEO_API_KEY: str = ""
    TWITTER_INFINITEO_API_SECRET: str = ""
    TWITTER_INFINITEO_ACCESS_TOKEN: str = ""
    TWITTER_INFINITEO_ACCESS_SECRET: str = ""

    # Twitter/X - YourOps
    TWITTER_YOUROPS_API_KEY: str = ""
    TWITTER_YOUROPS_API_SECRET: str = ""
    TWITTER_YOUROPS_ACCESS_TOKEN: str = ""
    TWITTER_YOUROPS_ACCESS_SECRET: str = ""

    # Token encryption
    TOKEN_ENCRYPTION_KEY: str = ""

    # Vercel API token (to update env vars when LinkedIn connects)
    VERCEL_TOKEN: str = ""
    VERCEL_PROJECT_ID: str = ""

    @property
    def is_vercel(self) -> bool:
        return bool(self.VERCEL)

    @property
    def fallback_models(self) -> list[str]:
        return [m.strip() for m in self.POLLINATIONS_FALLBACK_MODELS.split(",") if m.strip()]

    @property
    def linkedin_redirect_uri(self) -> str:
        """Build redirect URI from APP_URL if not explicitly set."""
        if self.LINKEDIN_REDIRECT_URI:
            return self.LINKEDIN_REDIRECT_URI
        return f"{self.APP_URL.rstrip('/')}/auth/linkedin/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
