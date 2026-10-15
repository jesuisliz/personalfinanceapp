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

    Which rule claims a transaction is decided by find_matching_rule: rules scoped
    to the transaction's account first, since generic bank statement text (e.g.
    "PAYMENT - THANK YOU") can carry no identifying info and would otherwise risk
    matching the same text on a different account; then global rules.

    Never overwrites a transaction that already has a clean_description — manual
    edits and prior rule applications are never clobbered. Safe to call repeatedly.

    Returns the number of transactions updated.
    """
    all_rules = session.execute(select(MerchantRule)).scalars().all()
    if not all_rules:
        return 0

    candidates = session.execute(
        select(Transaction).where(Transaction.clean_description.is_(None))
    ).scalars().all()

    updated = 0
    for transaction in candidates:
        rule = find_matching_rule(all_rules, transaction.description, transaction.account_id)
        if rule is None:
            continue
        transaction.clean_description = rule.clean_name
        if rule.category_id is not None and transaction.category_id is None:
            transaction.category_id = rule.category_id
        updated += 1

    session.commit()
    return updated


def find_matching_rule(rules, description: str, account_id: int) -> MerchantRule | None:
    """Return the rule that claims `description` on `account_id`, or None.

    Account-scoped rules for this account are checked before global rules; within a
    tier, rules are checked in ascending id, with an unsaved rule (id None) last.
    First case-insensitive substring match wins. Sorts itself; caller order is ignored.
    """
    description_lower = description.lower()

    def tier(scoped: bool):
        return sorted(
            (r for r in rules if (r.account_id == account_id if scoped else r.account_id is None)),
            key=lambda r: (r.id is None, r.id or 0),
        )

    for rule in tier(True) + tier(False):
        if rule.match_pattern.lower() in description_lower:
            return rule
    return None


def count_rule_wins(session: Session) -> dict[int, int]:
    """How many transactions each rule wins today, keyed by rule id.

    A rule wins a transaction when find_matching_rule picks it for that row's
    description and account, whether or not the row is already named - so this
    measures coverage (dead or shadowed rules show 0), not what applying the
    rules would change. Every rule is present.
    """
    rules = session.execute(select(MerchantRule)).scalars().all()
    counts = {rule.id: 0 for rule in rules}
    rows = session.execute(select(Transaction.description, Transaction.account_id)).all()
    for description, account_id in rows:
        rule = find_matching_rule(rules, description, account_id)
        if rule is not None:
            counts[rule.id] += 1
    return counts


def apply_all_rules(session: Session) -> None:
    """Apply merchant rules, then category rules - the one order used everywhere.

    Merchant rules go first: a specific merchant match is more accurate than a
    bank's generic raw_category, so it should win when both apply.
    """
    apply_merchant_rules(session)
    apply_category_rules(session)
