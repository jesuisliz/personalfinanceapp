from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Account, CurrentBalance, SavingsGoal, Transaction
from app.planning.aggregates import (
    apply_scenario_to_goal,
    apply_scenario_to_runway,
    average_monthly_expense,
    average_monthly_net_savings,
    compute_runway,
    get_current_balance_cents,
    project_goal_timeline,
)


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_account(session, name="Checking"):
    account = Account(name=name, institution="Bank of America", account_type="checking")
    session.add(account)
    session.commit()
    return account


_hash_counter = 0


def make_txn(session, account_id, amount_cents, txn_date, description="txn"):
    global _hash_counter
    _hash_counter += 1
    txn = Transaction(
        account_id=account_id,
        date=txn_date,
        description=description,
        amount_cents=amount_cents,
        source_row_hash=f"hash-{_hash_counter}",
    )
    session.add(txn)
    session.commit()
    return txn


def make_goal(session, name="Vacation", target_amount_cents=100000, saved_so_far_cents=0, target_date=None):
    goal = SavingsGoal(
        name=name,
        target_amount_cents=target_amount_cents,
        saved_so_far_cents=saved_so_far_cents,
        target_date=target_date,
    )
    session.add(goal)
    session.commit()
    return goal


# --- average_monthly_expense / average_monthly_net_savings ---


def test_average_monthly_expense_averages_over_trailing_months():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -10000, date(2026, 6, 1))
    make_txn(session, account.id, -20000, date(2026, 7, 1))

    assert average_monthly_expense(session, months=2, account_id=None) == 15000


def test_average_monthly_expense_zero_when_no_data():
    session = make_session()
    assert average_monthly_expense(session, months=6, account_id=None) == 0


def test_average_monthly_net_savings_includes_income():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, 100000, date(2026, 7, 1))  # income
    make_txn(session, account.id, -40000, date(2026, 7, 5))  # expense

    assert average_monthly_net_savings(session, months=1, account_id=None) == 60000


# --- get_current_balance_cents ---


def test_get_current_balance_cents_none_when_not_set():
    session = make_session()
    assert get_current_balance_cents(session) is None


def test_get_current_balance_cents_returns_amount():
    session = make_session()
    session.add(CurrentBalance(amount_cents=500000, updated_at=datetime(2026, 7, 27)))
    session.commit()
    assert get_current_balance_cents(session) == 500000


# --- compute_runway ---


def test_compute_runway_not_configured():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -10000, date(2026, 7, 1))

    result = compute_runway(session, current_balance_cents=None, months=1, account_id=None)

    assert result.balance_configured is False
    assert result.runway_months is None
    assert result.projected_end_date is None


def test_compute_runway_normal_case():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -100000, date(2026, 7, 15))  # avg monthly expense = $1000

    result = compute_runway(session, current_balance_cents=500000, months=1, account_id=None)

    assert result.balance_configured is True
    assert result.avg_monthly_expense_cents == 100000
    assert result.runway_months == 5.0
    assert result.projected_end_date is not None


def test_compute_runway_zero_expense_history():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, 100000, date(2026, 7, 1))  # only income, no expense

    result = compute_runway(session, current_balance_cents=500000, months=1, account_id=None)

    assert result.balance_configured is True
    assert result.avg_monthly_expense_cents == 0
    assert result.runway_months is None


# --- project_goal_timeline ---


def test_project_goal_timeline_on_track():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, 50000, date(2026, 7, 1))  # net savings = $500/mo
    goal = make_goal(session, target_amount_cents=200000, saved_so_far_cents=0)

    result = project_goal_timeline(session, goal, months=1, account_id=None)

    assert result.status == "on_track"
    assert result.avg_monthly_net_savings_cents == 50000
    assert result.remaining_cents == 200000
    assert result.months_to_goal == 4.0
    assert result.projected_date is not None


def test_project_goal_timeline_already_met():
    session = make_session()
    session_goal_account = make_account(session)
    make_txn(session, session_goal_account.id, 10000, date(2026, 7, 1))
    goal = make_goal(session, target_amount_cents=100000, saved_so_far_cents=150000)

    result = project_goal_timeline(session, goal, months=1, account_id=None)

    assert result.status == "already_met"
    assert result.months_to_goal == 0


def test_project_goal_timeline_not_on_track_when_net_savings_non_positive():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -10000, date(2026, 7, 1))  # net savings negative
    goal = make_goal(session, target_amount_cents=100000, saved_so_far_cents=0)

    result = project_goal_timeline(session, goal, months=1, account_id=None)

    assert result.status == "not_on_track"
    assert result.months_to_goal is None
    assert result.projected_date is None


# --- scenario composition ---


def test_apply_scenario_to_runway_extends_runway():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -100000, date(2026, 7, 15))  # avg expense $1000/mo

    baseline = compute_runway(session, current_balance_cents=500000, months=1, account_id=None)
    scenario = apply_scenario_to_runway(
        session, current_balance_cents=500000, extra_monthly_savings_cents=50000, months=1, account_id=None
    )

    assert scenario.avg_monthly_expense_cents == 50000  # 100000 - 50000
    assert scenario.runway_months == 10.0
    assert scenario.runway_months > baseline.runway_months


def test_apply_scenario_to_goal_accelerates_timeline():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, 50000, date(2026, 7, 1))  # net savings $500/mo
    goal = make_goal(session, target_amount_cents=200000, saved_so_far_cents=0)

    baseline = project_goal_timeline(session, goal, months=1, account_id=None)
    scenario = apply_scenario_to_goal(
        session, goal, extra_monthly_savings_cents=50000, months=1, account_id=None
    )

    assert scenario.avg_monthly_net_savings_cents == 100000  # 50000 + 50000
    assert scenario.months_to_goal == 2.0
    assert scenario.months_to_goal < baseline.months_to_goal
