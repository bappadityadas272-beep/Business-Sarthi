from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "version": "0.1.0", "dev_mode": s.dev_mode, "llm_provider": s.llm_provider}
