from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categories.apply import apply_merchant_rules
from app.db import get_db
from app.models import Category, MerchantRule
from app.schemas import MerchantRuleCreate, MerchantRuleOut

router = APIRouter()


@router.get("/merchant-rules", response_model=list[MerchantRuleOut])
def list_merchant_rules(db: Session = Depends(get_db)):
    return db.execute(select(MerchantRule).order_by(MerchantRule.id)).scalars().all()


@router.post("/merchant-rules", response_model=MerchantRuleOut)
def create_merchant_rule(body: MerchantRuleCreate, db: Session = Depends(get_db)):
    if body.category_id is not None and db.get(Category, body.category_id) is None:
        raise HTTPException(status_code=400, detail=f"Category {body.category_id} not found")

    rule = MerchantRule(
        match_pattern=body.match_pattern,
        clean_name=body.clean_name,
        category_id=body.category_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    # Apply immediately so existing transactions benefit right away, not just future imports.
    apply_merchant_rules(db)

    return rule
