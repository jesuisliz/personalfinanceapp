"""Support for turning a manual category edit into a MerchantRule.

See docs/lld_edit_creates_merchant_rule_claude.md section 4.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.categories.apply import find_matching_rule
from app.models import MerchantRule, Transaction

APPLE_PAY_PREFIX = "AplPay "
MIN_PATTERN_LENGTH = 4
SAMPLE_SIZE = 5


def normalize_rule_text(value: str) -> str:
    """Strip surrounding whitespace; reject a value that is blank afterwards.

    Used for both preview and create, so the pattern previewed is exactly the
    pattern stored.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def suggest_match_pattern(description: str) -> str:
    """Suggest a match_pattern for a rule built from `description`.

    A pre-fill only: the user sees and can edit it. The result is always a
    contiguous slice of `description`, so it always matches its own row.
    Algorithm (LLD 4.1): drop a leading "AplPay "; cut at " DES:"; else keep a
    single-token processor prefix plus the first word after its "*"; else keep
    the words before the first one containing a digit or "#". A result shorter
    than 4 characters falls back to the whole description.
    """
    start = len(APPLE_PAY_PREFIX) if description.startswith(APPLE_PAY_PREFIX) else 0
    body = description[start:]
    end = start + _suggested_body_end(body)
    pattern = description[start:end]
    if len(pattern) < MIN_PATTERN_LENGTH:
        return description
    return pattern


def _suggested_body_end(body: str) -> int:
    """Return the index in `body` where the suggested pattern ends."""
    des_index = body.find(" DES:")
    if des_index != -1:
        return des_index

    star = body.find("*")
    if star != -1 and _is_single_token(body[:star]):
        word_after_star = re.match(r"\s*\S+", body[star + 1:])
        if word_after_star is None:
            return star + 1
        return star + 1 + word_after_star.end()

    end = 0
    for token in re.finditer(r"\S+", body):
        if re.search(r"[\d#]", token.group()):
            break
        end = token.end()
    return end


def _is_single_token(text: str) -> bool:
    """True if `text`, stripped, is non-empty and has no internal whitespace."""
    stripped = text.strip()
    return bool(stripped) and not re.search(r"\s", stripped)


@dataclass
class CandidateEvaluation:
    """What a not-yet-saved rule would do. Counts follow LLD 4.2 step 5."""

    match_pattern: str
    matches_source: bool
    conflicting_rule: MerchantRule | None
    would_name_count: int
    would_categorize_count: int
    category_mismatch_count: int
    sample: list[Transaction]


def evaluate_candidate(
    session: Session,
    source: Transaction,
    match_pattern: str,
    category_id: int,
    this_account_only: bool,
) -> CandidateEvaluation:
    """Report what a rule built from `source` would do, without saving anything.

    The candidate is a transient MerchantRule (id None) never added to the session,
    so find_matching_rule ranks it as the newest rule of its tier - exactly where it
    would sit once saved. For each in-scope row, "candidate wins" means the
    candidate is the rule that would claim the row's description on a new import.
    The caller has already checked that `source` exists and has `category_id`.
    """
    candidate = MerchantRule(
        id=None,
        match_pattern=match_pattern,
        clean_name="",
        category_id=category_id,
        account_id=source.account_id if this_account_only else None,
    )
    existing_rules = session.execute(select(MerchantRule)).scalars().all()
    rules = [*existing_rules, candidate]

    matches_source = match_pattern.lower() in source.description.lower()
    conflicting_rule = None
    if matches_source:
        winner = find_matching_rule(rules, source.description, source.account_id)
        if winner is not candidate:
            conflicting_rule = winner

    in_scope = select(Transaction)
    if this_account_only:
        in_scope = in_scope.where(Transaction.account_id == source.account_id)
    won_rows = [
        txn
        for txn in session.execute(in_scope).scalars().all()
        if find_matching_rule(rules, txn.description, txn.account_id) is candidate
    ]

    def is_mismatch(txn: Transaction) -> bool:
        return txn.category_id is not None and txn.category_id != category_id

    named = [txn for txn in won_rows if txn.clean_description is None]
    newest_first = sorted(won_rows, key=lambda txn: (txn.date, txn.id), reverse=True)
    sample = sorted(newest_first, key=lambda txn: not is_mismatch(txn))[:SAMPLE_SIZE]

    return CandidateEvaluation(
        match_pattern=match_pattern,
        matches_source=matches_source,
        conflicting_rule=conflicting_rule,
        would_name_count=len(named),
        would_categorize_count=sum(1 for txn in named if txn.category_id is None),
        category_mismatch_count=sum(1 for txn in won_rows if is_mismatch(txn)),
        sample=sample,
    )
