from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.categories.seed import seed_categories
from app.db import Base
from app.imports.pipeline import import_file
from app.models import Account, Category, Transaction

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    yield s
    s.close()


def test_import_chase_creates_account_and_transactions(session):
    summary = import_file(session, "Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"))
    assert summary.rows_seen == 3
    assert summary.rows_inserted == 3
    assert summary.rows_skipped_as_duplicate == 0

    accounts = session.query(Account).all()
    assert len(accounts) == 1
    assert accounts[0].name == "Chase Sapphire (...3403)"
    assert session.query(Transaction).count() == 3


def test_reimporting_same_file_inserts_zero_new_rows(session):
    import_file(session, "Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"))
    summary = import_file(session, "Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"))

    assert summary.rows_inserted == 0
    assert summary.rows_skipped_as_duplicate == 3
    assert session.query(Transaction).count() == 3


def test_boa_splits_rows_into_four_accounts(session):
    summary = import_file(session, "ExportData_BOA.csv", read_fixture("boa_sample.csv"))

    accounts = {a.name: a.account_type for a in session.query(Account).all()}
    assert accounts == {
        "BOA Customized Cash Rewards": "credit_card",
        "BOA Travel Rewards Visa Signature": "credit_card",
        "BOA Interest Checking": "checking",
        "BOA Savings": "savings",
    }
    assert summary.rows_inserted == 6


def test_amex_repeated_rows_both_inserted_and_reimport_is_noop(session):
    first = import_file(session, "AmericanExpress_activity.csv", read_fixture("amex_sample.csv"))
    assert first.rows_inserted == 5  # includes both genuine $7.50 charges

    second = import_file(session, "AmericanExpress_activity.csv", read_fixture("amex_sample.csv"))
    assert second.rows_inserted == 0
    assert session.query(Transaction).count() == 5


def test_us_bank_single_account_both_credit_and_debit(session):
    summary = import_file(
        session, "US Bank - 8606_01-01-2026_06-30-2026.csv", read_fixture("us_bank_sample.csv")
    )
    assert summary.rows_inserted == 2
    accounts = session.query(Account).all()
    assert len(accounts) == 1
    assert accounts[0].name == "US Bank (...8606)"


def test_unmatched_filename_raises_instead_of_guessing(session):
    with pytest.raises(ValueError):
        import_file(session, "SomeRandomBank_export.csv", b"a,b\n1,2\n")


def test_import_automatically_applies_category_rules(session):
    seed_categories(session)
    import_file(session, "Chase3403_Activity_20260726.csv", read_fixture("chase_sample.csv"))

    doordash = session.query(Transaction).filter_by(description="DD *DOORDASH MAINELYNO").one()
    assert doordash.category_id is not None
    assert session.get(Category, doordash.category_id).name == "Dining & Drinks"

    payment = session.query(Transaction).filter_by(description="PAYMENT THANK YOU").one()
    assert session.get(Category, payment.category_id).name == "Transfers"
