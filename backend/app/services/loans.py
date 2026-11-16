"""Loan instalment dates (B-07, DEC-53). Dates only: no interest or balance maths."""
import calendar
from datetime import date


def due_in_month(year: int, month: int, due_day: int) -> date:
    """The due date in a month; a due day past the month end falls on the last day (31 -> 28 Feb)."""
    return date(year, month, min(due_day, calendar.monthrange(year, month)[1]))


def schedule(start_date: date, due_day: int, tenure_months: int) -> list[date]:
    """All instalment dates. The first is the first due date strictly after the start date, then one per month."""
    y, m = start_date.year, start_date.month
    if due_in_month(y, m, due_day) <= start_date:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    out = []
    for _ in range(tenure_months):
        out.append(due_in_month(y, m, due_day))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def status(start_date: date | None, due_day: int, tenure_months: int | None, emi: float, today: date) -> dict:
    """Next due date, instalments left and the remaining schedule. An instalment due today is still due."""
    if start_date is None or tenure_months is None:        # loans stored before DEC-53
        return {"next_due_date": None, "days_to_next_due": None, "instalments_total": None,
                "instalments_due_so_far": None, "instalments_left": None, "last_due_date": None, "schedule": []}
    dates = schedule(start_date, due_day, tenure_months)
    left = [d for d in dates if d >= today]
    nxt = left[0] if left else None
    done = tenure_months - len(left)
    return {"next_due_date": nxt, "days_to_next_due": (nxt - today).days if nxt else None,
            "instalments_total": tenure_months, "instalments_due_so_far": done, "instalments_left": len(left),
            "last_due_date": dates[-1],
            "schedule": [{"n": done + i + 1, "due_date": d, "emi": emi} for i, d in enumerate(left)]}
