from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Account
from app.schemas import AccountOut

router = APIRouter()


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.execute(select(Account).order_by(Account.name)).scalars().all()
