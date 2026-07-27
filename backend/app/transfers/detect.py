from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransferMatch

MATCH_WINDOW_DAYS = 3


def detect_transfers(session: Session) -> list[TransferMatch]:
    """Find candidate transfer pairs and record them as suggested TransferMatch rows.

    A candidate pair: two transactions on different accounts, exact opposite
    amount_cents, dated within MATCH_WINDOW_DAYS of each other. Transactions
    already part of a confirmed or rejected match are excluded from candidacy
    entirely (a decided transaction is settled, not up for re-matching). Pairs
    already suggested are not re-created.

    Returns the newly created TransferMatch rows (empty list if nothing new).
    """
    existing_matches = session.execute(select(TransferMatch)).scalars().all()
    decided_transaction_ids = {
        txn_id
        for m in existing_matches
        if m.status in ("confirmed", "rejected")
        for txn_id in (m.transaction_id_a, m.transaction_id_b)
    }
    existing_pairs = {(m.transaction_id_a, m.transaction_id_b) for m in existing_matches}

    candidates = session.execute(select(Transaction)).scalars().all()
    candidates = [t for t in candidates if t.id not in decided_transaction_ids]

    by_abs_amount: dict[int, list[Transaction]] = defaultdict(list)
    for txn in candidates:
        by_abs_amount[abs(txn.amount_cents)].append(txn)

    new_matches = []
    for group in by_abs_amount.values():
        if len(group) < 2:
            continue
        for i, txn_a in enumerate(group):
            for txn_b in group[i + 1 :]:
                if txn_a.account_id == txn_b.account_id:
                    continue
                if txn_a.amount_cents != -txn_b.amount_cents:
                    continue
                if abs((txn_a.date - txn_b.date).days) > MATCH_WINDOW_DAYS:
                    continue

                id_a, id_b = sorted((txn_a.id, txn_b.id))
                if (id_a, id_b) in existing_pairs:
                    continue

                match = TransferMatch(transaction_id_a=id_a, transaction_id_b=id_b, status="suggested")
                session.add(match)
                new_matches.append(match)
                existing_pairs.add((id_a, id_b))

    session.commit()
    return new_matches


def confirm_match(session: Session, match: TransferMatch) -> None:
    """Confirm a match: flag both transactions as transfers, and reject any
    other suggested match that references either transaction — a transaction
    can only be part of one real transfer pair."""
    match.status = "confirmed"

    for txn_id in (match.transaction_id_a, match.transaction_id_b):
        txn = session.get(Transaction, txn_id)
        txn.is_transfer = True

    other_suggested = session.execute(
        select(TransferMatch).where(
            TransferMatch.id != match.id,
            TransferMatch.status == "suggested",
        )
    ).scalars().all()
    for other in other_suggested:
        if match.transaction_id_a in (other.transaction_id_a, other.transaction_id_b) or match.transaction_id_b in (
            other.transaction_id_a,
            other.transaction_id_b,
        ):
            other.status = "rejected"

    session.commit()
