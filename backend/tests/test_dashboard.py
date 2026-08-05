from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.dashboard.aggregates import (
    category_breakdown,
    category_transactions,
    category_trends,
    estimate_category_reduction_savings,
    income_breakdown,
    income_transactions,
    merchant_transactions,
    monthly_summary,
    non_spending_category_transactions,
    top_merchants,
)
from app.db import Base
from app.models import Account, Category, Transaction


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_account(session, name="Checking"):
    account = Account(name=name, institution="Bank of America", account_type="checking")
    session.add(account)
    session.commit()
    return account


def make_category(session, name):
    category = Category(name=name)
    session.add(category)
    session.commit()
    return category


_hash_counter = 0


def make_txn(
    session,
    account_id,
    amount_cents,
    txn_date,
    description="txn",
    category_id=None,
    clean_description=None,
    is_transfer=False,
):
    global _hash_counter
    _hash_counter += 1
    txn = Transaction(
        account_id=account_id,
        date=txn_date,
        description=description,
        amount_cents=amount_cents,
        category_id=category_id,
        clean_description=clean_description,
        is_transfer=is_transfer,
        source_row_hash=f"hash-{_hash_counter}",
    )
    session.add(txn)
    session.commit()
    return txn


def test_monthly_summary_splits_income_and_expense():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, 500000, date(2026, 7, 5), description="paycheck")
    make_txn(session, account.id, -20000, date(2026, 7, 10), description="groceries")
    make_txn(session, account.id, -5000, date(2026, 7, 15), description="gas")

    result = monthly_summary(session, months=1, account_id=None)

    assert len(result) == 1
    row = result[0]
    assert row.month == "2026-07"
    assert row.income_cents == 500000
    assert row.expense_cents == 25000
    assert row.net_cents == 475000


def test_monthly_summary_zero_fills_months_with_no_transactions():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -1000, date(2026, 7, 5))

    result = monthly_summary(session, months=3, account_id=None)

    assert [r.month for r in result] == ["2026-05", "2026-06", "2026-07"]
    assert result[0].income_cents == 0
    assert result[0].expense_cents == 0
    assert result[1].income_cents == 0
    assert result[1].expense_cents == 0


def test_monthly_summary_returns_empty_when_no_data():
    session = make_session()
    assert monthly_summary(session, months=6, account_id=None) == []


def test_confirmed_transfer_excluded_from_monthly_totals():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -1000, date(2026, 7, 1), is_transfer=True)
    make_txn(session, account.id, -500, date(2026, 7, 2))  # real expense

    result = monthly_summary(session, months=1, account_id=None)

    assert result[0].expense_cents == 500


def test_unmatched_transfers_category_excluded_from_monthly_totals():
    session = make_session()
    account = make_account(session)
    transfers = make_category(session, "Transfers")
    # categorized as Transfers but not (yet) a confirmed is_transfer pair
    make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=transfers.id, is_transfer=False)
    make_txn(session, account.id, -500, date(2026, 7, 2))  # real expense

    result = monthly_summary(session, months=1, account_id=None)

    assert result[0].expense_cents == 500


def test_monthly_summary_filters_by_account():
    session = make_session()
    checking = make_account(session, "Checking")
    savings = make_account(session, "Savings")
    make_txn(session, checking.id, -1000, date(2026, 7, 1))
    make_txn(session, savings.id, -9999, date(2026, 7, 1))

    result = monthly_summary(session, months=1, account_id=checking.id)

    assert result[0].expense_cents == 1000


def test_category_breakdown_groups_null_as_uncategorized_and_expenses_only():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -3000, date(2026, 7, 1), category_id=dining.id)
    make_txn(session, account.id, -1500, date(2026, 7, 2), category_id=None)
    make_txn(session, account.id, 200000, date(2026, 7, 3), category_id=dining.id)  # income, excluded

    result = category_breakdown(session, "2026-07", account_id=None)

    by_name = {r.category_name: r.total_cents for r in result}
    assert by_name == {"Dining & Drinks": 3000, "Uncategorized": 1500}


def test_category_breakdown_excludes_transfers():
    session = make_session()
    account = make_account(session)
    transfers = make_category(session, "Transfers")
    make_txn(session, account.id, -50000, date(2026, 7, 1), category_id=transfers.id)
    make_txn(session, account.id, -1000, date(2026, 7, 1), is_transfer=True)

    result = category_breakdown(session, "2026-07", account_id=None)

    assert result == []


def test_category_breakdown_excludes_credit_card_payment():
    session = make_session()
    account = make_account(session)
    payments = make_category(session, "Credit Card Payment")
    make_txn(session, account.id, -50000, date(2026, 7, 1), category_id=payments.id)
    make_txn(session, account.id, -1000, date(2026, 7, 1), is_transfer=True)

    result = category_breakdown(session, "2026-07", account_id=None)

    assert result == []


def test_category_breakdown_sorted_descending_and_scoped_to_month():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    groceries = make_category(session, "Groceries")
    make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=dining.id)
    make_txn(session, account.id, -5000, date(2026, 7, 1), category_id=groceries.id)
    make_txn(session, account.id, -999999, date(2026, 6, 1), category_id=groceries.id)  # different month

    result = category_breakdown(session, "2026-07", account_id=None)

    assert [r.category_name for r in result] == ["Groceries", "Dining & Drinks"]


def test_top_merchants_groups_by_clean_description_falling_back_to_description():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -1000, date(2026, 7, 1), description="AMZN*1234", clean_description="Amazon")
    make_txn(session, account.id, -2000, date(2026, 7, 2), description="AMZN*5678", clean_description="Amazon")
    make_txn(session, account.id, -500, date(2026, 7, 3), description="Local Cafe")

    result = top_merchants(session, "2026-07", account_id=None, limit=10)

    by_name = {r.merchant: (r.total_cents, r.transaction_count) for r in result}
    assert by_name["Amazon"] == (3000, 2)
    assert by_name["Local Cafe"] == (500, 1)


def test_top_merchants_respects_limit():
    session = make_session()
    account = make_account(session)
    for i in range(5):
        make_txn(session, account.id, -(100 * (i + 1)), date(2026, 7, 1), description=f"Merchant {i}")

    result = top_merchants(session, "2026-07", account_id=None, limit=2)

    assert len(result) == 2
    assert result[0].total_cents == 500
    assert result[1].total_cents == 400


def test_category_transactions_returns_only_matching_category_and_month():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    groceries = make_category(session, "Groceries")
    a = make_txn(session, account.id, -1000, date(2026, 7, 1), description="Olive Garden", category_id=dining.id)
    make_txn(session, account.id, -2000, date(2026, 7, 2), description="Whole Foods", category_id=groceries.id)
    make_txn(session, account.id, -500, date(2026, 6, 1), description="Old dining", category_id=dining.id)

    result = category_transactions(session, "2026-07", account_id=None, category_id=dining.id, uncategorized=False)

    assert [t.id for t in result] == [a.id]


def test_category_transactions_all_time_when_month_omitted():
    """Regression test: a category spanning many months (e.g. a 7-month loan payment
    history) used to require one tool call per month, which could exceed the chatbot's
    tool-call round cap and silently return only a partial answer. month=None must
    return every matching transaction across all time in a single call instead."""
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    a = make_txn(session, account.id, -1000, date(2026, 1, 1), category_id=dining.id)
    b = make_txn(session, account.id, -2000, date(2026, 7, 1), category_id=dining.id)
    make_txn(session, account.id, -3000, date(2026, 7, 2), category_id=None)  # different category, excluded

    result = category_transactions(session, None, account_id=None, category_id=dining.id, uncategorized=False)

    assert {t.id for t in result} == {a.id, b.id}


def test_category_transactions_uncategorized_flag():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    a = make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=None)
    make_txn(session, account.id, -2000, date(2026, 7, 2), category_id=dining.id)

    result = category_transactions(session, "2026-07", account_id=None, category_id=None, uncategorized=True)

    assert [t.id for t in result] == [a.id]


def test_category_transactions_sums_to_category_breakdown_total():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=dining.id)
    make_txn(session, account.id, -2500, date(2026, 7, 15), category_id=dining.id)
    make_txn(session, account.id, 500000, date(2026, 7, 20), category_id=dining.id)  # income, excluded

    breakdown = category_breakdown(session, "2026-07", account_id=None)
    transactions = category_transactions(session, "2026-07", account_id=None, category_id=dining.id, uncategorized=False)

    dining_row = next(r for r in breakdown if r.category_id == dining.id)
    assert sum(-t.amount_cents for t in transactions) == dining_row.total_cents


def test_category_transactions_excludes_transfers():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=dining.id, is_transfer=True)

    result = category_transactions(session, "2026-07", account_id=None, category_id=dining.id, uncategorized=False)

    assert result == []


def test_income_breakdown_groups_by_category_and_income_only():
    session = make_session()
    account = make_account(session)
    income_cat = make_category(session, "Income")
    make_txn(session, account.id, 500000, date(2026, 7, 1), category_id=income_cat.id)
    make_txn(session, account.id, 100000, date(2026, 7, 2), category_id=None)
    make_txn(session, account.id, -3000, date(2026, 7, 3), category_id=income_cat.id)  # expense, excluded

    result = income_breakdown(session, "2026-07", account_id=None)

    by_name = {r.category_name: r.total_cents for r in result}
    assert by_name == {"Income": 500000, "Uncategorized": 100000}


def test_income_breakdown_includes_refund_in_spending_category():
    """A refund landing back in an ordinary spending category (e.g. "Shopping") must
    show up under its real category in the income breakdown, not be hidden or
    reclassified - per the user's explicit scope decision to mirror category_breakdown
    exactly rather than restrict to a hardcoded "true income" category allowlist."""
    session = make_session()
    account = make_account(session)
    shopping = make_category(session, "Shopping")
    make_txn(session, account.id, 4000, date(2026, 7, 1), category_id=shopping.id, description="Refund")

    result = income_breakdown(session, "2026-07", account_id=None)

    assert len(result) == 1
    assert result[0].category_id == shopping.id
    assert result[0].category_name == "Shopping"
    assert result[0].total_cents == 4000


def test_income_breakdown_excludes_transfers():
    session = make_session()
    account = make_account(session)
    transfers = make_category(session, "Transfers")
    make_txn(session, account.id, 50000, date(2026, 7, 1), category_id=transfers.id)
    make_txn(session, account.id, 1000, date(2026, 7, 1), is_transfer=True)

    result = income_breakdown(session, "2026-07", account_id=None)

    assert result == []


def test_income_breakdown_excludes_credit_card_payment():
    session = make_session()
    account = make_account(session)
    payments = make_category(session, "Credit Card Payment")
    make_txn(session, account.id, 50000, date(2026, 7, 1), category_id=payments.id)

    result = income_breakdown(session, "2026-07", account_id=None)

    assert result == []


def test_income_breakdown_sorted_descending_and_scoped_to_month():
    session = make_session()
    account = make_account(session)
    income_cat = make_category(session, "Income")
    interest = make_category(session, "Interest & Investments")
    make_txn(session, account.id, 1000, date(2026, 7, 1), category_id=interest.id)
    make_txn(session, account.id, 500000, date(2026, 7, 1), category_id=income_cat.id)
    make_txn(session, account.id, 999999, date(2026, 6, 1), category_id=interest.id)  # different month

    result = income_breakdown(session, "2026-07", account_id=None)

    assert [r.category_name for r in result] == ["Income", "Interest & Investments"]


def test_income_transactions_returns_only_matching_category_and_month():
    session = make_session()
    account = make_account(session)
    income_cat = make_category(session, "Income")
    interest = make_category(session, "Interest & Investments")
    a = make_txn(session, account.id, 500000, date(2026, 7, 1), description="Paycheck", category_id=income_cat.id)
    make_txn(session, account.id, 1000, date(2026, 7, 2), description="Interest", category_id=interest.id)
    make_txn(session, account.id, 500000, date(2026, 6, 1), description="Old paycheck", category_id=income_cat.id)

    result = income_transactions(session, "2026-07", account_id=None, category_id=income_cat.id, uncategorized=False)

    assert [t.id for t in result] == [a.id]


def test_income_transactions_all_time_when_month_omitted():
    session = make_session()
    account = make_account(session)
    income_cat = make_category(session, "Income")
    a = make_txn(session, account.id, 500000, date(2026, 1, 1), category_id=income_cat.id)
    b = make_txn(session, account.id, 500000, date(2026, 7, 1), category_id=income_cat.id)

    result = income_transactions(session, None, account_id=None, category_id=income_cat.id, uncategorized=False)

    assert {t.id for t in result} == {a.id, b.id}


def test_income_transactions_uncategorized_flag():
    session = make_session()
    account = make_account(session)
    income_cat = make_category(session, "Income")
    a = make_txn(session, account.id, 100000, date(2026, 7, 1), category_id=None)
    make_txn(session, account.id, 500000, date(2026, 7, 2), category_id=income_cat.id)

    result = income_transactions(session, "2026-07", account_id=None, category_id=None, uncategorized=True)

    assert [t.id for t in result] == [a.id]


def test_income_transactions_sums_to_income_breakdown_total():
    session = make_session()
    account = make_account(session)
    income_cat = make_category(session, "Income")
    make_txn(session, account.id, 300000, date(2026, 7, 1), category_id=income_cat.id)
    make_txn(session, account.id, 200000, date(2026, 7, 15), category_id=income_cat.id)
    make_txn(session, account.id, -1000, date(2026, 7, 20), category_id=income_cat.id)  # expense, excluded

    breakdown = income_breakdown(session, "2026-07", account_id=None)
    transactions = income_transactions(session, "2026-07", account_id=None, category_id=income_cat.id, uncategorized=False)

    income_row = next(r for r in breakdown if r.category_id == income_cat.id)
    assert sum(t.amount_cents for t in transactions) == income_row.total_cents


def test_income_transactions_excludes_transfers():
    session = make_session()
    account = make_account(session)
    income_cat = make_category(session, "Income")
    make_txn(session, account.id, 1000, date(2026, 7, 1), category_id=income_cat.id, is_transfer=True)

    result = income_transactions(session, "2026-07", account_id=None, category_id=income_cat.id, uncategorized=False)

    assert result == []


def test_non_spending_category_transactions_includes_both_directions():
    """Unlike category_transactions, this must show a category like "Credit Card
    Payment" or "Transfers" directly - including confirmed is_transfer pairs and
    positive (incoming) amounts - since those categories have no spending total in
    category_breakdown for a caller to be consistent with."""
    session = make_session()
    account = make_account(session)
    payments = make_category(session, "Credit Card Payment")
    outgoing = make_txn(
        session, account.id, -20000, date(2026, 7, 5), description="Payment to Card", category_id=payments.id,
        is_transfer=True,
    )
    incoming = make_txn(
        session, account.id, 20000, date(2026, 7, 5), description="Card Payment Received", category_id=payments.id,
        is_transfer=True,
    )
    make_txn(session, account.id, -500, date(2026, 6, 1), category_id=payments.id)  # different month, excluded

    result = non_spending_category_transactions(session, "2026-07", account_id=None, category_id=payments.id)

    assert {t.id for t in result} == {outgoing.id, incoming.id}


def test_non_spending_category_transactions_scoped_by_account():
    session = make_session()
    checking = make_account(session, "Checking")
    savings = make_account(session, "Savings")
    payments = make_category(session, "Credit Card Payment")
    checking_txn = make_txn(session, checking.id, -20000, date(2026, 7, 5), category_id=payments.id)
    make_txn(session, savings.id, 20000, date(2026, 7, 5), category_id=payments.id)

    result = non_spending_category_transactions(session, "2026-07", account_id=checking.id, category_id=payments.id)

    assert [t.id for t in result] == [checking_txn.id]


def test_non_spending_category_transactions_all_time_when_month_omitted():
    session = make_session()
    account = make_account(session)
    payments = make_category(session, "Credit Card Payment")
    a = make_txn(session, account.id, -20000, date(2026, 1, 5), category_id=payments.id)
    b = make_txn(session, account.id, -20000, date(2026, 7, 5), category_id=payments.id)

    result = non_spending_category_transactions(session, None, account_id=None, category_id=payments.id)

    assert {t.id for t in result} == {a.id, b.id}


def test_category_trends_returns_one_breakdown_per_trailing_month():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -1000, date(2026, 6, 1), category_id=dining.id)
    make_txn(session, account.id, -3000, date(2026, 7, 1), category_id=dining.id)

    trends = category_trends(session, months=2, account_id=None)

    assert set(trends.keys()) == {"2026-06", "2026-07"}
    assert trends["2026-06"][0].total_cents == 1000
    assert trends["2026-07"][0].total_cents == 3000


def test_category_trends_empty_when_no_data():
    session = make_session()
    assert category_trends(session, months=6, account_id=None) == {}


def test_estimate_savings_averages_over_trailing_months_and_applies_percent():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -10000, date(2026, 6, 1), category_id=dining.id)  # $100
    make_txn(session, account.id, -20000, date(2026, 7, 1), category_id=dining.id)  # $200

    result = estimate_category_reduction_savings(
        session, category_id=dining.id, uncategorized=False, reduction_percent=25, months=2, account_id=None
    )

    # avg = (10000 + 20000) / 2 = 15000; 25% of that = 3750/month, *12 = 45000/year
    assert result.avg_monthly_cents == 15000
    assert result.monthly_savings_cents == 3750
    assert result.annual_savings_cents == 45000
    assert result.months_considered == 2


def test_estimate_savings_uncategorized_flag():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -10000, date(2026, 7, 1), category_id=None)

    result = estimate_category_reduction_savings(
        session, category_id=None, uncategorized=True, reduction_percent=50, months=1, account_id=None
    )

    assert result.avg_monthly_cents == 10000
    assert result.monthly_savings_cents == 5000


def test_estimate_savings_zero_fills_months_with_no_spend_in_that_category():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -10000, date(2026, 7, 1), category_id=dining.id)  # only July has dining spend

    result = estimate_category_reduction_savings(
        session, category_id=dining.id, uncategorized=False, reduction_percent=100, months=2, account_id=None
    )

    # June has zero dining spend, so avg = 10000 / 2 = 5000, not 10000
    assert result.avg_monthly_cents == 5000


def test_merchant_transactions_matches_case_insensitive_substring():
    session = make_session()
    account = make_account(session)
    a = make_txn(session, account.id, -50000, date(2026, 7, 6), description="The Vanguard Group")
    b = make_txn(
        session, account.id, -50000, date(2026, 1, 5),
        description="VANGUARD BUY DES:INVESTMENT ID:999", clean_description="Vanguard Investment Purchase",
    )
    make_txn(session, account.id, -1000, date(2026, 7, 1), description="Olive Garden")

    result = merchant_transactions(session, "vanguard", months=None, account_id=None)

    assert {t.id for t in result} == {a.id, b.id}


def test_merchant_transactions_matches_clean_description_not_just_raw():
    """A search term that only appears in the cleaned-up description (not the raw
    bank text) must still match - clean_description is what the search checks first,
    the same convention as the Transactions page's own Merchant filter."""
    session = make_session()
    account = make_account(session)
    a = make_txn(
        session, account.id, -50000, date(2026, 7, 1),
        description="VANGUARD BUY DES:INVESTMENT ID:999", clean_description="Vanguard Investment Purchase",
    )

    result = merchant_transactions(session, "vanguard", months=None, account_id=None)

    assert [t.id for t in result] == [a.id]


def test_merchant_transactions_scoped_to_trailing_months():
    session = make_session()
    account = make_account(session)
    recent = make_txn(session, account.id, -50000, date(2026, 7, 6), description="The Vanguard Group")
    make_txn(session, account.id, -50000, date(2026, 1, 5), description="The Vanguard Group")  # outside window

    result = merchant_transactions(session, "vanguard", months=1, account_id=None)

    assert [t.id for t in result] == [recent.id]


def test_merchant_transactions_all_time_when_months_omitted():
    session = make_session()
    account = make_account(session)
    a = make_txn(session, account.id, -50000, date(2026, 1, 5), description="The Vanguard Group")
    b = make_txn(session, account.id, -50000, date(2026, 7, 6), description="The Vanguard Group")

    result = merchant_transactions(session, "vanguard", months=None, account_id=None)

    assert {t.id for t in result} == {a.id, b.id}


def test_merchant_transactions_includes_transfers_unlike_category_transactions():
    """Unlike category_transactions, a merchant/payee search must include is_transfer
    rows - the question is about a real-world counterparty, not a spending category."""
    session = make_session()
    account = make_account(session)
    a = make_txn(session, account.id, -50000, date(2026, 7, 6), description="The Vanguard Group", is_transfer=True)

    result = merchant_transactions(session, "vanguard", months=None, account_id=None)

    assert [t.id for t in result] == [a.id]


def test_merchant_transactions_scoped_by_account():
    session = make_session()
    checking = make_account(session, "Checking")
    savings = make_account(session, "Savings")
    checking_txn = make_txn(session, checking.id, -50000, date(2026, 7, 6), description="The Vanguard Group")
    make_txn(session, savings.id, -50000, date(2026, 7, 6), description="The Vanguard Group")

    result = merchant_transactions(session, "vanguard", months=None, account_id=checking.id)

    assert [t.id for t in result] == [checking_txn.id]


def test_merchant_transactions_empty_when_no_data():
    session = make_session()
    assert merchant_transactions(session, "vanguard", months=6, account_id=None) == []
