"""Loans and the EMI schedule (B-07, DEC-53)."""
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import Db, OwnShop, OwnShopConsented
from app.models import Loan
from app.schemas.records import LoanIn, LoanOut
from app.services import clock, loans

router = APIRouter(prefix="/shops", tags=["loans"])


def loan_out(loan: Loan) -> dict:
    return {"id": loan.id, "principal": loan.principal, "emi": loan.emi, "due_day": loan.due_day,
            "start_date": loan.start_date, "tenure_months": loan.tenure_months,
            **loans.status(loan.start_date, loan.due_day, loan.tenure_months, loan.emi, clock.today())}


@router.get("/{shop_id}/loans", response_model=list[LoanOut])
def list_loans(shop: OwnShop, db: Db) -> list[dict]:
    return [loan_out(x) for x in db.scalars(select(Loan).where(Loan.shop_id == shop.id).order_by(Loan.id))]


@router.post("/{shop_id}/loans", response_model=LoanOut, status_code=201)
def add_loan(body: LoanIn, shop: OwnShopConsented, db: Db) -> dict:
    loan = Loan(shop_id=shop.id, **body.model_dump())
    db.add(loan)
    db.commit()
    return loan_out(loan)
