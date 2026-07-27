from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Category, Transaction
from app.schemas import TransactionOut, TransactionUpdate

router = APIRouter()


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    account_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Transaction)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    stmt = stmt.order_by(Transaction.date.desc()).offset(offset).limit(limit)
    return db.execute(stmt).scalars().all()


@router.patch("/transactions/{transaction_id}", response_model=TransactionOut)
def update_transaction(transaction_id: int, body: TransactionUpdate, db: Session = Depends(get_db)):
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

    updates = body.model_dump(exclude_unset=True)

    if "category_id" in updates and updates["category_id"] is not None:
        category = db.get(Category, updates["category_id"])
        if category is None:
            raise HTTPException(status_code=400, detail=f"Category {updates['category_id']} not found")

    for field, value in updates.items():
        setattr(transaction, field, value)

    db.commit()
    db.refresh(transaction)
    return transaction
