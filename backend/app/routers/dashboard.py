from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dashboard.aggregates import (
    category_breakdown,
    category_transactions,
    income_breakdown,
    income_transactions,
    monthly_summary,
    top_merchants,
)
from app.db import get_db
from app.schemas import CategoryBreakdownOut, MerchantBreakdownOut, MonthlySummaryOut, TransactionOut

router = APIRouter(prefix="/dashboard")


@router.get("/monthly", response_model=list[MonthlySummaryOut])
def get_monthly_summary(
    months: int = Query(default=6, ge=1, le=24),
    account_id: int | None = None,
    db: Session = Depends(get_db),
):
    return monthly_summary(db, months, account_id)


@router.get("/categories", response_model=list[CategoryBreakdownOut])
def get_category_breakdown(month: str | None = None, account_id: int | None = None, db: Session = Depends(get_db)):
    return category_breakdown(db, month, account_id)


@router.get("/merchants", response_model=list[MerchantBreakdownOut])
def get_top_merchants(
    month: str | None = None,
    account_id: int | None = None,
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return top_merchants(db, month, account_id, limit)


@router.get("/categories/transactions", response_model=list[TransactionOut])
def get_category_transactions(
    month: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    uncategorized: bool = False,
    db: Session = Depends(get_db),
):
    return category_transactions(db, month, account_id, category_id, uncategorized)


@router.get("/income-categories", response_model=list[CategoryBreakdownOut])
def get_income_breakdown(month: str | None = None, account_id: int | None = None, db: Session = Depends(get_db)):
    return income_breakdown(db, month, account_id)


@router.get("/income-categories/transactions", response_model=list[TransactionOut])
def get_income_transactions(
    month: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    uncategorized: bool = False,
    db: Session = Depends(get_db),
):
    return income_transactions(db, month, account_id, category_id, uncategorized)
