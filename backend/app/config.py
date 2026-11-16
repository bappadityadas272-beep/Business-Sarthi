"""Settings loaded from environment variables and the repo-root .env file.

Empty values in .env are ignored, so the defaults below apply (see .env.example).
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DEV_JWT_SECRET = "dev-only-change-me-not-a-secret-placeholder"   # refused when DEV_MODE is off (DEC-41)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_ignore_empty=True, extra="ignore"
    )

    dev_mode: bool = True
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'sarthi.db').as_posix()}"
    jwt_secret: str = DEV_JWT_SECRET
    llm_provider: Literal["gemini", "claude", "stub"] = "stub"
    llm_api_key: str = ""
    embed_model: str = "intfloat/multilingual-e5-small"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    app_user_agent: str = "BusinessSarthi/0.1 (prototype)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
