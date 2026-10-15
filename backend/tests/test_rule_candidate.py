from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.categories.candidate import evaluate_candidate, normalize_rule_text, suggest_match_pattern
from app.db import Base
from app.models import Account, Category, MerchantRule, Transaction


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("AplPay WALGREENS LAS VEGAS NV", "WALGREENS LAS VEGAS NV"),
        ("PRUDENTIAL DES:EDI PYMNTS ID:1", "PRUDENTIAL"),
        ("SQ *7-ELEVEN 1234", "SQ *7-ELEVEN"),
        ("PM *iDrama 555", "PM *iDrama"),
        ("TST* TATTE BAKERY BOSTON MA", "TST* TATTE"),
        ("IC* INSTACART SAN FRANCISCOCA", "IC* INSTACART"),
        ("UBER   *TRIP HELP.UBER.COM", "UBER   *TRIP"),
        ("VZWRLSS*APOCC VISN 04/21", "VZWRLSS*APOCC"),
        ("TRADER JOE S #519 PORTLAND ME", "TRADER JOE S"),
        (
            "Online scheduled transfer from CHK 1962 Confirmation# 1",
            "Online scheduled transfer from CHK",
        ),
        ("MACYS  ROCKINGHAM PK", "MACYS  ROCKINGHAM PK"),
        ("ONLINE STORE * 99", "ONLINE STORE *"),
        ("7-ELEVEN 33012 BOSTON", "7-ELEVEN 33012 BOSTON"),
        ("AplPay SQ", "AplPay SQ"),
        ("KFC J123 TOKYO", "KFC J123 TOKYO"),
        ("ACME*", "ACME*"),
        ("BLUE BOTTLE  DES:X", "BLUE BOTTLE"),
        ("AplPay   FOO 123", "AplPay   FOO 123"),  # "  FOO" strips to 3 chars: whole description
        ("  PADDED SHOP  ", "PADDED SHOP"),
        ("  AB 12  ", "AB 12"),  # cut "AB" is too short: whole description, stripped
    ],
)
def test_suggest_match_pattern(description, expected):
    result = suggest_match_pattern(description)

    assert result == expected
    assert result.lower() in description.lower()


def test_normalize_rule_text_strips_whitespace():
    assert normalize_rule_text("  KURA  ") == "KURA"


@pytest.mark.parametrize("value", ["", "   "])
def test_normalize_rule_text_rejects_blank(value):
    with pytest.raises(ValueError):
        normalize_rule_text(value)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def add_transaction(session, account_id, description, clean=None, category_id=None, day=1):
    txn = Transaction(
        account_id=account_id,
        date=date(2026, 1, day),
        description=description,
        amount_cents=-1000,
        source_row_hash=f"hash-{account_id}-{description}-{day}",
        clean_description=clean,
        category_id=category_id,
    )
    session.add(txn)
    session.commit()
    return txn


def add_rule(session, pattern, category_id, account_id=None):
    rule = MerchantRule(
        match_pattern=pattern, clean_name=pattern.title(), category_id=category_id, account_id=account_id
    )
    session.add(rule)
    session.commit()
    return rule


@pytest.fixture
def kura():
    """Two accounts, three categories, one older rule and five rows (see the plan, Task 3)."""
    session = make_session()
    session.add_all([
        Account(id=1, name="Card A", institution="Chase", account_type="credit_card"),
        Account(id=2, name="Card B", institution="Amex", account_type="credit_card"),
        Category(id=1, name="Dining"),
        Category(id=2, name="Travel"),
        Category(id=3, name="Groceries"),
    ])
    session.commit()
    rows = SimpleNamespace(
        old_rule=add_rule(session, "KURA OLD", category_id=3),
        src=add_transaction(session, 1, "SQ *KURA REVOLVING SUSHI", category_id=1, day=5),
        blank=add_transaction(session, 1, "SQ *KURA REVOLVING SUSHI #2", day=4),
        other_acct=add_transaction(session, 2, "SQ *KURA REVOLVING", day=3),
        renamed_travel=add_transaction(session, 1, "SQ *KURA TRAVEL", clean="My name", category_id=2, day=2),
        owned=add_transaction(session, 1, "SQ *KURA OLD TOWN", category_id=3, day=1),
    )
    return session, rows


DINING = 1


def test_evaluate_global_candidate_counts(kura):
    session, rows = kura

    result = evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=False)

    assert result.match_pattern == "SQ *KURA"
    assert result.matches_source is True
    assert result.conflicting_rule is None
    assert result.would_name_count == 3  # src, blank, other_acct; owned stays with the older rule
    assert result.would_categorize_count == 2  # blank, other_acct; never the source row itself
    assert result.category_mismatch_count == 1  # renamed_travel
    assert [txn.id for txn in result.sample] == [
        rows.renamed_travel.id, rows.src.id, rows.blank.id, rows.other_acct.id
    ]


def test_evaluate_this_account_only_excludes_other_account_and_beats_older_global(kura):
    session, rows = kura

    result = evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=True)

    assert result.would_name_count == 3  # src, blank, owned (account tier beats global "KURA OLD")
    assert result.would_categorize_count == 1  # blank
    assert result.category_mismatch_count == 2  # renamed_travel, owned
    assert rows.other_acct.id not in [txn.id for txn in result.sample]


def test_evaluate_renamed_row_counts_nothing_when_older_rule_wins(kura):
    session, rows = kura
    add_rule(session, "KURA TRAVEL", category_id=2)

    result = evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=False)

    assert result.category_mismatch_count == 0
    assert rows.renamed_travel.id not in [txn.id for txn in result.sample]


def test_evaluate_non_matching_pattern_is_not_a_conflict(kura):
    session, rows = kura
    add_rule(session, "KURA REV", category_id=3)  # an existing rule that does match the source

    result = evaluate_candidate(session, rows.src, "WALMART", DINING, this_account_only=False)

    assert result.matches_source is False
    assert result.conflicting_rule is None


def test_evaluate_conflict_only_for_global_candidate(kura):
    session, rows = kura
    existing = add_rule(session, "SQ *KURA REV", category_id=3)

    global_result = evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=False)
    scoped_result = evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=True)

    assert global_result.conflicting_rule is existing
    assert scoped_result.conflicting_rule is None


def test_evaluate_sample_capped_at_five_mismatches_first_then_newest(kura):
    session, rows = kura
    extra = [add_transaction(session, 1, f"SQ *KURA VISIT {n}", day=10 + n) for n in range(6)]
    same_day = add_transaction(session, 1, "SQ *KURA VISIT TIE", day=15)

    result = evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=False)

    assert [txn.id for txn in result.sample] == [
        rows.renamed_travel.id, same_day.id, extra[5].id, extra[4].id, extra[3].id
    ]


def test_evaluate_is_read_only(kura):
    session, rows = kura
    rule_count = session.scalar(select(func.count()).select_from(MerchantRule))
    txn_count = session.scalar(select(func.count()).select_from(Transaction))

    evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=False)

    assert not session.new
    assert not session.dirty
    assert session.scalar(select(func.count()).select_from(MerchantRule)) == rule_count
    assert session.scalar(select(func.count()).select_from(Transaction)) == txn_count
    session.expire_all()
    assert rows.blank.clean_description is None
    assert rows.blank.category_id is None


def test_evaluate_categorize_count_only_over_rows_it_names(kura):
    """A row with a name already set but no category is won by the candidate, yet the
    candidate doesn't name it, so apply_merchant_rules never categorizes it either."""
    session, rows = kura
    add_transaction(session, 1, "SQ *KURA RENAMED", clean="Mine", day=6)

    result = evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=False)

    assert result.would_name_count == 3
    assert result.would_categorize_count == 2


def test_evaluate_rule_scoped_to_another_account_never_wins(kura):
    session, rows = kura
    add_rule(session, "SQ *KURA", category_id=3, account_id=2)

    result = evaluate_candidate(session, rows.src, "SQ *KURA REV", DINING, this_account_only=False)

    assert result.conflicting_rule is None
    assert result.would_name_count == 2  # src, blank; other_acct stays with its account-2 rule
    assert rows.other_acct.id not in [txn.id for txn in result.sample]


def test_evaluate_never_commits_or_flushes_changes(kura, monkeypatch):
    session, rows = kura
    flushed = []
    event.listen(session, "before_flush", lambda *args: flushed.append(True))

    def fail_commit():
        raise AssertionError("evaluate_candidate committed")

    def fail_flush(*args, **kwargs):
        raise AssertionError("evaluate_candidate flushed")

    session.autoflush = False  # so any flush below is an explicit call, not a query's autoflush
    monkeypatch.setattr(session, "commit", fail_commit)
    monkeypatch.setattr(session, "flush", fail_flush)

    evaluate_candidate(session, rows.src, "SQ *KURA", DINING, this_account_only=False)

    assert flushed == []
