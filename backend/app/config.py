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
    scheduler_enabled: bool = True                   # in-process daily job (B-09); the tests switch it off
    scheduler_interval_minutes: int = 60             # how often the job looks; the work itself is once a day
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'sarthi.db').as_posix()}"
    jwt_secret: str = DEV_JWT_SECRET
    llm_provider: Literal["gemini", "claude", "stub"] = "stub"
    llm_api_key: str = ""                            # never logged (DEC-75)
    llm_model: str = ""                              # empty = the provider's default model
    llm_fallback_model: str = ""                     # empty = provider default fallback (DEC-81); "off" = none
    llm_timeout_s: float = 20.0
    llm_max_retries: int = 3
    embed_model: str = "intfloat/multilingual-e5-small"
    kb_path: str = (REPO_ROOT / "data" / "kb" / "schemes.json").as_posix()        # written by the team (D-03)
    kb_index_dir: str = (BACKEND_DIR / "data" / "kb_index").as_posix()           # generated, git-ignored
    kb_embedder: Literal["auto", "e5", "fallback"] = "auto"   # DEC-85: auto = e5 if installed, else fallback
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    app_user_agent: str = "BusinessSarthi/0.1 (prototype)"
    osm_mode: Literal["mock", "live"] = "mock"       # DEC-47: mock answers by default, no network
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"   # comma-separated; no wildcard (DEC-90)
    max_body_bytes: int = 65536                       # larger request bodies get 413 (DEC-90)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip() and o.strip() != "*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
