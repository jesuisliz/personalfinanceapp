from datetime import date
from pathlib import Path

import pytest

from app.imports.amex import AmexParser
from app.imports.base import compute_row_hashes
from app.imports.boa import BoaParser
from app.imports.chase import ChaseParser
from app.imports.us_bank import UsBankParser

FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_chase_parses_dates_and_signed_amount():
    rows = ChaseParser().parse(read_fixture("chase_sample.csv"))
    assert len(rows) == 3
    first = rows[0]
    assert first.date == date(2026, 7, 22)
    assert first.posted_date == date(2026, 7, 23)
    assert first.amount_cents == -3575
    assert first.raw_category == "Food & Drink"


def test_chase_unescapes_html_entities_in_description():
    rows = ChaseParser().parse(read_fixture("chase_sample.csv"))
    assert rows[1].description == "BARNES & NOBLE #2052"


def test_chase_positive_amount_for_payment():
    rows = ChaseParser().parse(read_fixture("chase_sample.csv"))
    assert rows[2].amount_cents == 150000


def test_chase_synthesizes_payment_raw_category_when_blank():
    # Confirmed against real data: Chase leaves Category blank on Payment-type
    # rows. Without this, these rows would be permanently uncategorized.
    rows = ChaseParser().parse(read_fixture("chase_sample.csv"))
    assert rows[2].raw_category == "Payment"


def test_chase_does_not_synthesize_category_for_non_payment_blank_rows():
    csv_bytes = (
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "07/01/2026,07/02/2026,SOME ADJUSTMENT,,Adjustment,-5.00,\n"
    ).encode("utf-8")
    rows = ChaseParser().parse(csv_bytes)
    assert rows[0].raw_category is None


def test_boa_strips_bom_and_parses_comma_amount():
    rows = BoaParser().parse(read_fixture("boa_sample.csv"))
    assert len(rows) == 6
    transfer_row = rows[1]
    assert transfer_row.amount_cents == -428466
    refund_row = rows[2]
    assert refund_row.amount_cents == 428466


def test_boa_pending_has_no_posted_date_posted_does():
    rows = BoaParser().parse(read_fixture("boa_sample.csv"))
    assert rows[0].posted_date is None  # pending
    assert rows[1].posted_date == date(2026, 7, 23)  # posted


def test_boa_account_match_key_distinguishes_accounts():
    rows = BoaParser().parse(read_fixture("boa_sample.csv"))
    assert "Credit Card" in rows[0].account_match_key
    assert "Bofa Interest Checking" in rows[1].account_match_key


def test_boa_uses_simple_description():
    rows = BoaParser().parse(read_fixture("boa_sample.csv"))
    assert rows[0].description == "Olive Garden"


def test_us_bank_credit_is_positive():
    rows = UsBankParser().parse(read_fixture("us_bank_sample.csv"))
    credit_row = rows[0]
    assert credit_row.amount_cents == 22000
    assert credit_row.date == date(2026, 6, 18)
    assert credit_row.description == "PAYMENT THANK YOU"


def test_us_bank_debit_is_negative():
    rows = UsBankParser().parse(read_fixture("us_bank_sample.csv"))
    debit_row = rows[1]
    assert debit_row.amount_cents == -4520


def test_us_bank_unrecognized_transaction_type_raises():
    bad_csv = (
        '"Date","Transaction","Name","Memo","Amount"\n'
        '"2026-01-01","REFUND","SOMETHING","","10.00"\n'
    ).encode("utf-8")
    with pytest.raises(ValueError):
        UsBankParser().parse(bad_csv)


def test_amex_sign_is_inverted_from_source():
    rows = AmexParser().parse(read_fixture("amex_sample.csv"))
    payment_row = rows[0]
    assert payment_row.amount_cents == 24307  # source -243.07 (payment) -> positive (income)


def test_amex_charge_becomes_negative():
    rows = AmexParser().parse(read_fixture("amex_sample.csv"))
    charge_row = rows[2]  # source 334.37 (charge) -> negative (expense)
    assert charge_row.amount_cents == -33437


def test_amex_collapses_padded_whitespace_in_description():
    rows = AmexParser().parse(read_fixture("amex_sample.csv"))
    assert rows[1].description == "THE CLARIDGE HOTEL ATLANTIC CITY NJ"


def test_amex_identical_same_day_rows_both_parse():
    # Two genuinely separate charges with the same date/amount/description.
    # The parser itself must not drop either — dedupe collision risk is a
    # pipeline-level concern (see LLD Section 11), not a parsing concern.
    rows = AmexParser().parse(read_fixture("amex_sample.csv"))
    duplicates = [r for r in rows if r.description.startswith("AplPay NYX")]
    assert len(duplicates) == 2


def test_compute_row_hashes_gives_distinct_hashes_for_genuine_repeats():
    rows = AmexParser().parse(read_fixture("amex_sample.csv"))
    hashes = compute_row_hashes(account_id=1, rows=rows)
    assert len(hashes) == len(rows)
    assert len(set(hashes)) == len(rows)  # all unique, including the repeated $7.50 pair


def test_chase_malformed_row_error_includes_row_number_and_raw_content():
    bad_csv = (
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "07/22/2026,07/23/2026,DD *DOORDASH MAINELYNO,Food & Drink,Sale,-35.75,\n"
        "not-a-date,07/25/2026,BAD ROW,Shopping,Sale,-10.00,\n"
    ).encode("utf-8")
    with pytest.raises(ValueError) as excinfo:
        ChaseParser().parse(bad_csv)
    assert "row 3" in str(excinfo.value)
    assert "BAD ROW" in str(excinfo.value)


def test_compute_row_hashes_is_stable_across_reimport_of_same_file():
    rows = AmexParser().parse(read_fixture("amex_sample.csv"))
    first_import = compute_row_hashes(account_id=1, rows=rows)
    second_import = compute_row_hashes(account_id=1, rows=rows)
    assert first_import == second_import
