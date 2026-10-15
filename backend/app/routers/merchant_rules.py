from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categories.apply import apply_merchant_rules, count_rule_wins
from app.categories.candidate import CandidateEvaluation, evaluate_candidate, suggest_match_pattern
from app.db import get_db
from app.models import Account, Category, MerchantRule, Transaction
from app.schemas import (
    MerchantRuleCreate,
    MerchantRuleListItem,
    MerchantRuleOut,
    MerchantRulePreviewOut,
    MerchantRulePreviewRequest,
    SampleRowOut,
)

router = APIRouter()


def refuse(status_code: int, code: str, message: str, **extra) -> HTTPException:
    """An HTTPException whose detail the rule panel can read: {code, message, ...}."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def load_source_row(db: Session, transaction_id: int, category_id: int) -> Transaction:
    """Return the edited row a rule is being remembered from, or refuse.

    409 when the row's category is no longer the one the rule would assign: the user
    changed it again after the panel opened, and saving would recategorize it.
    """
    source = db.get(Transaction, transaction_id)
    if source is None:
        raise refuse(404, "source_not_found", f"Transaction {transaction_id} not found")
    if source.category_id != category_id:
        raise refuse(
            409, "source_category_changed", "This transaction's category changed since the rule was suggested"
        )
    return source


def sample_rows(db: Session, evaluation: CandidateEvaluation) -> list[SampleRowOut]:
    """The evaluation's sample rows with category names for display."""
    category_names = dict(db.execute(select(Category.id, Category.name)).all())
    return [
        SampleRowOut(
            id=txn.id,
            date=txn.date,
            description=txn.description,
            category_name=category_names.get(txn.category_id),
        )
        for txn in evaluation.sample
    ]


@router.get("/merchant-rules", response_model=list[MerchantRuleListItem])
def list_merchant_rules(db: Session = Depends(get_db)):
    counts = count_rule_wins(db)
    rules = db.execute(select(MerchantRule).order_by(MerchantRule.id)).scalars().all()
    return [
        MerchantRuleListItem(**MerchantRuleOut.model_validate(rule).model_dump(), match_count=counts.get(rule.id, 0))
        for rule in rules
    ]


@router.post("/merchant-rules/preview", response_model=MerchantRulePreviewOut)
def preview_merchant_rule(body: MerchantRulePreviewRequest, db: Session = Depends(get_db)):
    """Report what a rule remembered from a category edit would do. Read-only."""
    source = load_source_row(db, body.source_transaction_id, body.category_id)
    match_pattern = body.match_pattern or suggest_match_pattern(source.description)
    if not match_pattern:
        raise refuse(422, "no_suggested_pattern", "This transaction has no description to suggest a pattern from")
    evaluation = evaluate_candidate(db, source, match_pattern, body.category_id, body.this_account_only)
    return MerchantRulePreviewOut(
        match_pattern=evaluation.match_pattern,
        matches_source=evaluation.matches_source,
        conflicting_rule=evaluation.conflicting_rule,
        would_name_count=evaluation.would_name_count,
        would_categorize_count=evaluation.would_categorize_count,
        category_mismatch_count=evaluation.category_mismatch_count,
        sample=sample_rows(db, evaluation),
    )


@router.post("/merchant-rules", response_model=MerchantRuleOut)
def create_merchant_rule(body: MerchantRuleCreate, db: Session = Depends(get_db)):
    if body.source_transaction_id is not None:
        account_id = check_rule_from_source(db, body)
    else:
        if body.category_id is not None and db.get(Category, body.category_id) is None:
            raise HTTPException(status_code=400, detail=f"Category {body.category_id} not found")
        if body.account_id is not None and db.get(Account, body.account_id) is None:
            raise HTTPException(status_code=400, detail=f"Account {body.account_id} not found")
        account_id = body.account_id

    rule = MerchantRule(
        match_pattern=body.match_pattern,
        clean_name=body.clean_name,
        category_id=body.category_id,
        account_id=account_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    # Apply immediately so existing transactions benefit right away, not just future imports.
    apply_merchant_rules(db)

    return rule


def check_rule_from_source(db: Session, body: MerchantRuleCreate) -> int | None:
    """Refuse a rule remembered from a category edit if it would be unsafe; return its account_id.

    Refusals in order: source missing (404), source category changed (409), category
    or (when scoped) account doesn't exist (400 - SQLite FKs are off, so the source
    row proves neither), pattern doesn't match the source (400), an existing rule
    would still win the source (409 conflict), rows the rule would win already have
    another category (409).
    """
    source = load_source_row(db, body.source_transaction_id, body.category_id)
    if db.get(Category, body.category_id) is None:
        raise refuse(400, "category_not_found", f"Category {body.category_id} not found")
    if body.this_account_only and db.get(Account, source.account_id) is None:
        raise refuse(400, "account_not_found", f"Account {source.account_id} not found")
    evaluation = evaluate_candidate(db, source, body.match_pattern, body.category_id, body.this_account_only)
    if not evaluation.matches_source:
        raise refuse(400, "pattern_not_matching_source", "The pattern doesn't match this transaction")
    if evaluation.conflicting_rule is not None:
        raise refuse(
            409,
            "conflict",
            "An existing rule already names this transaction",
            rule=MerchantRuleOut.model_validate(evaluation.conflicting_rule).model_dump(),
        )
    if evaluation.category_mismatch_count:
        raise refuse(
            409,
            "category_mismatch",
            "Some transactions this rule would match are in a different category",
            count=evaluation.category_mismatch_count,
            sample=[row.model_dump(mode="json") for row in sample_rows(db, evaluation)],
        )
    return source.account_id if body.this_account_only else None


@router.delete("/merchant-rules/{rule_id}", status_code=204)
def delete_merchant_rule(rule_id: int, db: Session = Depends(get_db)):
    """Delete a rule. Rows it already filled keep their name and category."""
    rule = db.get(MerchantRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Merchant rule {rule_id} not found")
    db.delete(rule)
    db.commit()
    return Response(status_code=204)
