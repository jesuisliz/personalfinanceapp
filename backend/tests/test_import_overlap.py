"""Import overlap guard through import_file (LLD tests 7-14, plus R1/R2 from the Phase 2 plan).

Existing rows are always created by a real earlier import, the way they arise in practice.
"""
import hashlib
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.imports.pipeline import SuspectedDuplicate, import_file
from app.models import Account, Category, MerchantRule, Transaction

CHASE_FILE = "Chase3403_Activity_20260726.csv"
AGGREGATOR_FILE = "ExportData_BOA.csv"
NATIVE_9837_FILE = "ExportData_BOA_Aug2026_9837.csv"

AGGREGATOR_HEADER = (
    "Status,Date,Original Description,Split Type,Category,Currency,Amount,"
    "User Description,Memo,Classification,Account Name,Simple Description"
)
AGGREGATOR_ACCOUNT_NAMES = {
    "cash": "Bank of America - Credit Card - Customized Cash Rewards World Mastercard",
    "checking": "Bank of America - Bank - Bofa Interest Checking",
    "savings": "Bank of America - Bank - Credit",
}


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def chase_csv(*rows: tuple[str, str, str]) -> bytes:
    """Chase export; each row is (MM/DD/YYYY, description, amount)."""
    lines = ["Transaction Date,Post Date,Description,Category,Type,Amount,Memo"]
    lines += [f"{day},{day},{description},Shopping,Sale,{amount}," for day, description, amount in rows]
    return ("\n".join(lines) + "\n").encode()


def aggregator_csv(*rows: tuple[str, str, str, str]) -> bytes:
    """BOA aggregator export; each row is (account key, MM/DD/YYYY, description, amount)."""
    lines = [AGGREGATOR_HEADER]
    lines += [
        f"posted,{day}, {description},,Shopping,USD,{amount}, , ,Personal,"
        f"{AGGREGATOR_ACCOUNT_NAMES[key]}, {description}"
        for key, day, description, amount in rows
    ]
    return ("\n".join(lines) + "\n").encode()


def native_card_csv(*rows: tuple[str, str, str]) -> bytes:
    """BOA native card export; each row is (MM/DD/YYYY, payee, amount)."""
    lines = ["Posted Date,Reference Number,Payee,Address,Amount"]
    lines += [f'{day},0000,"{payee}","",{amount}' for day, payee, amount in rows]
    return ("\n".join(lines) + "\n").encode()


def expected_hash(account_id: int, iso_date: str, amount_cents: int, description: str) -> str:
    """Row hash built by hand from the documented key format, not via compute_row_hashes."""
    key = f"{account_id}|{iso_date}|{amount_cents}|{description.lower()}|0"
    return hashlib.sha256(key.encode()).hexdigest()


def assert_counts(summary, inserted: int, skipped: int, held: int) -> None:
    assert summary.rows_inserted == inserted
    assert summary.rows_skipped_as_duplicate == skipped
    assert summary.rows_held_as_suspected_duplicate == held
    assert summary.rows_seen == inserted + skipped + held
    assert len(summary.suspected_duplicates) == held


def txn(session, description: str, amount_cents: int) -> Transaction:
    return session.query(Transaction).filter_by(description=description, amount_cents=amount_cents).one()


def account_id(session, name: str) -> int:
    return session.query(Account).filter_by(name=name).one().id


# Test 7
def test_reimporting_identical_file_skips_every_row_and_holds_none(session):
    csv = chase_csv(
        ("07/10/2026", "HANNAFORD 1", "-34.50"),
        ("07/11/2026", "HANNAFORD 2", "-34.50"),
        ("07/09/2026", "SHELL", "-40.00"),
    )
    import_file(session, CHASE_FILE, csv)

    summary = import_file(session, CHASE_FILE, csv)

    assert_counts(summary, inserted=0, skipped=3, held=0)


# Test 8
def test_hash_matched_row_claims_its_existing_row(session):
    import_file(session, CHASE_FILE, chase_csv(("07/10/2026", "HANNAFORD", "-34.50")))

    summary = import_file(
        session,
        CHASE_FILE,
        chase_csv(("07/11/2026", "HANNAFORD STORE", "-34.50"), ("07/10/2026", "HANNAFORD", "-34.50")),
    )

    assert_counts(summary, inserted=1, skipped=1, held=0)
    assert session.query(Transaction).filter_by(description="HANNAFORD STORE").count() == 1


# Test 9
def test_rows_in_the_same_file_are_never_paired_with_each_other(session):
    import_file(session, CHASE_FILE, chase_csv(("07/20/2026", "NETFLIX", "-15.49")))  # inside the window

    summary = import_file(
        session,
        CHASE_FILE,
        chase_csv(("07/20/2026", "METRO FARE", "-2.75"), ("07/21/2026", "METRO FARE", "-2.75")),
    )

    assert_counts(summary, inserted=2, skipped=0, held=0)


# Test 10 (+ Review Focus 3: exact 3-day edges)
def test_window_query_is_padded_per_account_inclusive_at_three_days(session):
    import_file(
        session,
        AGGREGATOR_FILE,
        aggregator_csv(
            ("cash", "03/09/2026", "CAFE A", "-12.00"),  # 3 days before cash's earliest new date
            ("checking", "09/21/2026", "UTILITY X", "-80.00"),  # 3 days after checking's latest
            ("savings", "06/15/2026", "TRANSFER S", "250.00"),  # inside the file-wide range only
            ("cash", "03/08/2026", "CAFE B", "-7.00"),  # 4 days before: never pairs
        ),
    )

    summary = import_file(
        session,
        AGGREGATOR_FILE,
        aggregator_csv(
            ("checking", "09/18/2026", "UTILITY X PAYMENT", "-80.00"),
            ("checking", "09/01/2026", "GROCER", "-30.00"),
            ("cash", "03/12/2026", "CAFE A LLC", "-12.00"),
            ("cash", "03/12/2026", "CAFE B LLC", "-7.00"),
            ("cash", "03/30/2026", "BOOKS", "-20.00"),
            ("savings", "01/05/2026", "TRANSFER S2", "250.00"),
            ("savings", "01/02/2026", "INTEREST", "0.35"),
        ),
    )

    assert_counts(summary, inserted=5, skipped=0, held=2)
    partners = {s.description: s.existing_id for s in summary.suspected_duplicates}
    assert partners == {
        "CAFE A LLC": txn(session, "CAFE A", -1200).id,
        "UTILITY X PAYMENT": txn(session, "UTILITY X", -8000).id,
    }


AGGREGATOR_ROWS = (
    ("cash", "07/25/2026", "Olive Garden", "-59.07"),
    ("cash", "07/23/2026", "The Home Depot", "-50.58"),
    ("checking", "07/22/2026", "Payment to Discover Card", "-120.00"),
    ("cash", "07/25/2026", "Barnes & Noble", "-26.92"),
    ("cash", "07/23/2026", "The Home Depot", "29.52"),
    ("cash", "07/20/2026", "IKEA", "-54.65"),
)

NATIVE_ROWS = (  # newest-first, as BOA native card exports are
    ("08/02/2026", "SHELL OIL 57444", "-40.00"),
    ("07/22/2026", "CVS PHARMACY 1234", "-120.00"),  # same amount/date as a checking row
    ("07/27/2026", "OLIVE GARDEN ZK 002143", "-59.07"),  # 2-day shift
    ("07/27/2026", "BARNES & NOBLE #2988", "-26.92"),  # 2-day shift
    ("07/23/2026", "THE HOME DEPOT #2401", "29.52"),
    ("07/23/2026", "THE HOME DEPOT #2401", "-50.58"),
    ("07/20/2026", "IKEA STOUGHTON", "-54.65"),
)


def expected_incident_suspects(session) -> list[SuspectedDuplicate]:
    cash_id = account_id(session, "BOA Customized Cash Rewards")

    def suspect(iso_date, description, cents, existing_description):
        existing = txn(session, existing_description, cents)
        return SuspectedDuplicate(
            row_hash=expected_hash(cash_id, iso_date, cents, description),
            account_name="BOA Customized Cash Rewards",
            date=date.fromisoformat(iso_date),
            description=description,
            amount_cents=cents,
            existing_id=existing.id,
            existing_date=existing.date,
            existing_description=existing_description,
        )

    return [
        suspect("2026-07-20", "IKEA STOUGHTON", -5465, "IKEA"),
        suspect("2026-07-23", "THE HOME DEPOT #2401", -5058, "The Home Depot"),
        suspect("2026-07-23", "THE HOME DEPOT #2401", 2952, "The Home Depot"),
        suspect("2026-07-27", "BARNES & NOBLE #2988", -2692, "Barnes & Noble"),
        suspect("2026-07-27", "OLIVE GARDEN ZK 002143", -5907, "Olive Garden"),
    ]


# Test 11 (+ Review Focus 1: re-import keeps held rows held)
def test_cross_format_incident_holds_every_overlapping_row(session):
    import_file(session, AGGREGATOR_FILE, aggregator_csv(*AGGREGATOR_ROWS))

    first = import_file(session, NATIVE_9837_FILE, native_card_csv(*NATIVE_ROWS))

    assert_counts(first, inserted=2, skipped=0, held=5)
    assert first.suspected_duplicates == expected_incident_suspects(session)
    cash_id = account_id(session, "BOA Customized Cash Rewards")
    inserted = {t.description for t in session.query(Transaction).filter_by(account_id=cash_id)}
    assert {"SHELL OIL 57444", "CVS PHARMACY 1234"} <= inserted
    assert "IKEA STOUGHTON" not in inserted

    second = import_file(session, NATIVE_9837_FILE, native_card_csv(*NATIVE_ROWS))

    assert_counts(second, inserted=0, skipped=2, held=5)
    assert second.suspected_duplicates == first.suspected_duplicates


# R2 (Review Focus 2)
def test_file_order_does_not_change_the_summary(session):
    import_file(session, AGGREGATOR_FILE, aggregator_csv(*AGGREGATOR_ROWS))

    summary = import_file(session, NATIVE_9837_FILE, native_card_csv(*reversed(NATIVE_ROWS)))

    assert_counts(summary, inserted=2, skipped=0, held=5)
    assert summary.suspected_duplicates == expected_incident_suspects(session)


EXISTING_THREE = (
    ("07/10/2026", "HANNAFORD", "-34.50"),
    ("07/12/2026", "SHELL", "-40.00"),
    ("07/15/2026", "NETFLIX", "-15.49"),
)
NEW_THREE = (
    ("07/11/2026", "HANNAFORD #8354", "-34.50"),
    ("07/14/2026", "SHELL OIL", "-40.00"),
    ("07/15/2026", "NETFLIX.COM", "-15.49"),
)


def hold_three(session):
    """Import EXISTING_THREE, then NEW_THREE; return the summary that holds all three."""
    import_file(session, CHASE_FILE, chase_csv(*EXISTING_THREE))
    summary = import_file(session, CHASE_FILE, chase_csv(*NEW_THREE))
    assert_counts(summary, inserted=0, skipped=0, held=3)
    return summary


def hashes_for(summary, *descriptions: str) -> frozenset[str]:
    return frozenset(s.row_hash for s in summary.suspected_duplicates if s.description in descriptions)


# Test 12
def test_accepting_two_of_three_inserts_exactly_those_two(session):
    first = hold_three(session)
    shell_partner = next(s.existing_id for s in first.suspected_duplicates if s.description == "SHELL OIL")

    second = import_file(
        session,
        CHASE_FILE,
        chase_csv(*NEW_THREE),
        accept_hashes=hashes_for(first, "HANNAFORD #8354", "NETFLIX.COM"),
    )

    assert_counts(second, inserted=2, skipped=0, held=1)
    assert [(s.description, s.existing_id) for s in second.suspected_duplicates] == [("SHELL OIL", shell_partner)]
    descriptions = {t.description for t in session.query(Transaction)}
    assert descriptions == {"HANNAFORD", "SHELL", "NETFLIX", "HANNAFORD #8354", "NETFLIX.COM"}

    third = import_file(session, CHASE_FILE, chase_csv(*NEW_THREE))
    assert_counts(third, inserted=0, skipped=2, held=1)
    assert third.suspected_duplicates == second.suspected_duplicates


# Test 13
def test_unknown_accept_hash_is_ignored(session):
    first = hold_three(session)

    second = import_file(
        session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=frozenset({"not-a-real-hash"})
    )

    assert_counts(second, inserted=0, skipped=0, held=3)
    assert second.suspected_duplicates == first.suspected_duplicates


# R1 (Review Focus 4)
def test_accepting_an_already_inserted_hash_changes_nothing(session):
    first = hold_three(session)
    accepted = hashes_for(first, "HANNAFORD #8354")
    import_file(session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=accepted)

    again = import_file(session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=accepted)

    assert_counts(again, inserted=0, skipped=1, held=2)
    assert session.query(Transaction).count() == 4


# Test 14
def test_accepted_row_gets_its_category_from_rules(session):
    groceries = Category(name="Groceries")
    session.add(groceries)
    session.flush()
    session.add(MerchantRule(match_pattern="HANNAFORD #8354", clean_name="Hannaford", category_id=groceries.id))
    session.commit()
    first = hold_three(session)

    import_file(
        session, CHASE_FILE, chase_csv(*NEW_THREE), accept_hashes=hashes_for(first, "HANNAFORD #8354")
    )

    assert txn(session, "HANNAFORD #8354", -3450).category_id == groceries.id
