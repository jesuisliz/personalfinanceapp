from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Account, Transaction, TransferMatch
from app.transfers.detect import confirm_match, detect_transfers


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_account(session, name):
    account = Account(name=name, institution="Bank of America", account_type="checking")
    session.add(account)
    session.commit()
    return account


def make_txn(session, account_id, amount_cents, txn_date, description="txn", hash_suffix=None):
    txn = Transaction(
        account_id=account_id,
        date=txn_date,
        description=description,
        amount_cents=amount_cents,
        source_row_hash=f"hash-{hash_suffix or (account_id, amount_cents, txn_date)}",
    )
    session.add(txn)
    session.commit()
    return txn


def test_detects_opposite_amount_pair_across_accounts():
    session = make_session()
    checking = make_account(session, "Checking")
    credit_card = make_account(session, "Credit Card")
    a = make_txn(session, checking.id, -428466, date(2026, 7, 23))
    b = make_txn(session, credit_card.id, 428466, date(2026, 7, 23))

    matches = detect_transfers(session)

    assert len(matches) == 1
    assert {matches[0].transaction_id_a, matches[0].transaction_id_b} == {a.id, b.id}
    assert matches[0].status == "suggested"


def test_does_not_match_within_same_account():
    session = make_session()
    checking = make_account(session, "Checking")
    make_txn(session, checking.id, -1000, date(2026, 1, 1))
    make_txn(session, checking.id, 1000, date(2026, 1, 1))

    matches = detect_transfers(session)

    assert matches == []


def test_does_not_match_beyond_window():
    session = make_session()
    checking = make_account(session, "Checking")
    credit_card = make_account(session, "Credit Card")
    make_txn(session, checking.id, -1000, date(2026, 1, 1))
    make_txn(session, credit_card.id, 1000, date(2026, 1, 10))  # far outside 3-day window

    matches = detect_transfers(session)

    assert matches == []


def test_running_detection_twice_does_not_duplicate():
    session = make_session()
    checking = make_account(session, "Checking")
    credit_card = make_account(session, "Credit Card")
    make_txn(session, checking.id, -1000, date(2026, 1, 1))
    make_txn(session, credit_card.id, 1000, date(2026, 1, 1))

    detect_transfers(session)
    second_run = detect_transfers(session)

    assert second_run == []
    assert session.query(TransferMatch).count() == 1


def test_confirm_sets_is_transfer_on_both_sides():
    session = make_session()
    checking = make_account(session, "Checking")
    credit_card = make_account(session, "Credit Card")
    a = make_txn(session, checking.id, -1000, date(2026, 1, 1))
    b = make_txn(session, credit_card.id, 1000, date(2026, 1, 1))

    matches = detect_transfers(session)
    confirm_match(session, matches[0])

    session.refresh(a)
    session.refresh(b)
    assert a.is_transfer is True
    assert b.is_transfer is True


def test_confirming_one_match_rejects_other_candidates_on_same_transaction():
    session = make_session()
    checking = make_account(session, "Checking")
    credit_card = make_account(session, "Credit Card")
    savings = make_account(session, "Savings")

    # transaction `a` has two plausible matches: b and c (ambiguous, same amount/window)
    a = make_txn(session, checking.id, -1000, date(2026, 1, 1))
    b = make_txn(session, credit_card.id, 1000, date(2026, 1, 1))
    c = make_txn(session, savings.id, 1000, date(2026, 1, 2))

    matches = detect_transfers(session)
    assert len(matches) == 2  # a-b and a-c both suggested

    match_with_b = next(m for m in matches if b.id in (m.transaction_id_a, m.transaction_id_b))
    confirm_match(session, match_with_b)

    other_match = next(m for m in matches if m.id != match_with_b.id)
    session.refresh(other_match)
    assert other_match.status == "rejected"


def test_confirmed_and_rejected_transactions_excluded_from_future_candidacy():
    session = make_session()
    checking = make_account(session, "Checking")
    credit_card = make_account(session, "Credit Card")
    a = make_txn(session, checking.id, -1000, date(2026, 1, 1))
    b = make_txn(session, credit_card.id, 1000, date(2026, 1, 1))

    matches = detect_transfers(session)
    confirm_match(session, matches[0])

    # a new, unrelated transaction on a third account with the same amount should not
    # generate a new candidate against the already-decided `a` or `b`.
    savings = make_account(session, "Savings")
    make_txn(session, savings.id, 1000, date(2026, 1, 1))

    new_matches = detect_transfers(session)
    assert new_matches == []
