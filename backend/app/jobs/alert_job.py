"""Daily alert check for one shop (B-09): the same service the refresh endpoint calls."""
from datetime import date

from sqlalchemy.orm import Session

from app.models import Shop
from app.services import alerts as alert_service


def run(db: Session, shop: Shop, day: date) -> int:
    """Returns the number of alerts raised."""
    return alert_service.refresh(db, shop, day)["raised"]
