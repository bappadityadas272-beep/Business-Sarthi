"""Shared schema types."""
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BeforeValidator


def _as_utc(v):
    """SQLite returns naive datetimes; everything we store is UTC, so say so in API output."""
    if isinstance(v, datetime):
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)
    return v


UtcDatetime = Annotated[datetime, BeforeValidator(_as_utc)]
