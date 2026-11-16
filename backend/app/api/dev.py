"""Demo-only tools, refused unless DEV_MODE is on (B-09). Never switch DEV_MODE on in a real deployment."""
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Db
from app.config import get_settings
from app.jobs import scheduler
from app.services import clock

router = APIRouter(prefix="/dev", tags=["dev"])


class AdvanceIn(BaseModel):
    days: int = Field(ge=1, le=400)


class AdvanceOut(BaseModel):
    today: date
    days_advanced: int
    alerts_raised: int
    reviews_created: int
    errors: int
    is_demo_clock: bool = True


class ClockOut(BaseModel):
    today: date
    dev_mode: bool


def _dev_only() -> None:
    if not get_settings().dev_mode:
        raise HTTPException(403, detail={"code": "dev_mode_off"})


@router.get("/clock", response_model=ClockOut)
def read_clock() -> dict:
    """The app's idea of today (it differs from the real date after `advance-time`)."""
    return {"today": clock.today(), "dev_mode": get_settings().dev_mode}


@router.post("/advance-time", response_model=AdvanceOut)
def advance_time(body: AdvanceIn, user: CurrentUser, db: Db) -> dict:
    """Move the app clock forward and run the daily job for every day passed, so alerts and due reviews appear
    as they would have. The clock lives in memory: restarting the server puts it back to the real date."""
    _dev_only()
    start = clock.today()
    clock.advance(body.days)
    total = {"alerts_raised": 0, "reviews_created": 0, "errors": 0}
    for i in range(1, body.days + 1):
        day = scheduler.run_day(db, start + timedelta(days=i))
        for k in total:
            total[k] += day[k]
    return {"today": clock.today(), "days_advanced": body.days, **total}
