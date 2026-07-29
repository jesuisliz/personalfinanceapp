from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, CategoryRule, MerchantRule, Transaction


def apply_category_rules(session: Session) -> int:
    """Assign category_id to transactions that don't have one yet, based on
    (account.institution, transaction.raw_category) matching a CategoryRule.
    A rule scoped to a specific account_id takes priority over an
    institution-wide rule for the same raw_category, since one account can
    reuse a raw_category to mean something different than it does elsewhere
    at the same institution.

    Never overwrites a transaction that already has a category_id — manual
    edits and prior rule applications are never clobbered, so this is safe to
    call repeatedly (after every import, or on startup).

    Returns the number of transactions updated.
    """
    uncategorized = session.execute(
        select(Transaction, Account.institution)
        .join(Account, Transaction.account_id == Account.id)
        .where(Transaction.category_id.is_(None), Transaction.raw_category.is_not(None))
    ).all()

    all_rules = session.execute(select(CategoryRule)).scalars().all()
    account_rules = {
        (rule.account_id, rule.raw_category): rule.category_id
        for rule in all_rules
        if rule.account_id is not None
    }
    institution_rules = {
        (rule.institution, rule.raw_category): rule.category_id
        for rule in all_rules
        if rule.account_id is None
    }

    updated = 0
    for transaction, institution in uncategorized:
        category_id = account_rules.get((transaction.account_id, transaction.raw_category))
        if category_id is None:
            category_id = institution_rules.get((institution, transaction.raw_category))
        if category_id is not None:
            transaction.category_id = category_id
            updated += 1

    session.commit()
    return updated


def apply_merchant_rules(session: Session) -> int:
    """Assign clean_description (and category_id, if the rule specifies one and
    the transaction doesn't already have one) based on a case-insensitive
    substring match of MerchantRule.match_pattern against Transaction.description.

    A rule scoped to a specific account_id is checked before any account-wide
    (account_id is None) rule, since generic bank statement text (e.g. "PAYMENT -
    THANK YOU") can carry no identifying info and would otherwise risk matching
    the same text on a different account. Within each tier, first matching rule
    wins (rules are checked in id order).

    Never overwrites a transaction that already has a clean_description — manual
    edits and prior rule applications are never clobbered. Safe to call repeatedly.

    Returns the number of transactions updated.
    """
    all_rules = session.execute(select(MerchantRule).order_by(MerchantRule.id)).scalars().all()
    if not all_rules:
        return 0

    account_rules = [rule for rule in all_rules if rule.account_id is not None]
    global_rules = [rule for rule in all_rules if rule.account_id is None]

    candidates = session.execute(
        select(Transaction).where(Transaction.clean_description.is_(None))
    ).scalars().all()

    updated = 0
    for transaction in candidates:
        description_lower = transaction.description.lower()
        applicable_rules = [
            rule for rule in account_rules if rule.account_id == transaction.account_id
        ] + global_rules
        for rule in applicable_rules:
            if rule.match_pattern.lower() in description_lower:
                transaction.clean_description = rule.clean_name
                if rule.category_id is not None and transaction.category_id is None:
                    transaction.category_id = rule.category_id
                updated += 1
                break

    session.commit()
    return updated
