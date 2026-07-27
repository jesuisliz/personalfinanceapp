from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dashboard.aggregates import latest_transaction_date, monthly_summary
from app.models import CurrentBalance, SavingsGoal
from app.schemas import GoalProjectionOut, RunwayOut

DAYS_PER_MONTH = 30.44


def _add_months(start: date, months: float) -> date:
    return start + timedelta(days=round(months * DAYS_PER_MONTH))


def get_current_balance_cents(session: Session) -> int | None:
    row = session.execute(select(CurrentBalance)).scalars().first()
    return row.amount_cents if row else None


def average_monthly_expense(session: Session, months: int, account_id: int | None) -> int:
    rows = monthly_summary(session, months, account_id)
    if not rows:
        return 0
    return sum(r.expense_cents for r in rows) // len(rows)


def average_monthly_net_savings(session: Session, months: int, account_id: int | None) -> int:
    rows = monthly_summary(session, months, account_id)
    if not rows:
        return 0
    return sum(r.net_cents for r in rows) // len(rows)


def _project_runway(
    session: Session,
    current_balance_cents: int | None,
    avg_monthly_expense_cents: int,
    account_id: int | None,
) -> RunwayOut:
    if current_balance_cents is None:
        return RunwayOut(
            balance_configured=False,
            current_balance_cents=None,
            avg_monthly_expense_cents=avg_monthly_expense_cents,
            runway_months=None,
            projected_end_date=None,
        )

    if avg_monthly_expense_cents <= 0:
        # No historical expense signal (or the scenario zeroed it out) -- can't divide,
        # and that's a real "not enough signal" state, not infinite runway.
        return RunwayOut(
            balance_configured=True,
            current_balance_cents=current_balance_cents,
            avg_monthly_expense_cents=avg_monthly_expense_cents,
            runway_months=None,
            projected_end_date=None,
        )

    runway_months = current_balance_cents / avg_monthly_expense_cents
    latest = latest_transaction_date(session, account_id)
    return RunwayOut(
        balance_configured=True,
        current_balance_cents=current_balance_cents,
        avg_monthly_expense_cents=avg_monthly_expense_cents,
        runway_months=runway_months,
        projected_end_date=_add_months(latest, runway_months) if latest else None,
    )


def compute_runway(
    session: Session, current_balance_cents: int | None, months: int, account_id: int | None
) -> RunwayOut:
    avg_expense = average_monthly_expense(session, months, account_id)
    return _project_runway(session, current_balance_cents, avg_expense, account_id)


def apply_scenario_to_runway(
    session: Session,
    current_balance_cents: int | None,
    extra_monthly_savings_cents: int,
    months: int,
    account_id: int | None,
) -> RunwayOut:
    """Same projection as `compute_runway`, but with the scenario's extra monthly
    savings reducing the average monthly expense used -- spending less extends runway."""
    avg_expense = average_monthly_expense(session, months, account_id)
    adjusted_expense = max(0, avg_expense - extra_monthly_savings_cents)
    return _project_runway(session, current_balance_cents, adjusted_expense, account_id)


def _project_goal(
    session: Session, goal: SavingsGoal, avg_monthly_net_savings_cents: int, account_id: int | None
) -> GoalProjectionOut:
    remaining_cents = goal.target_amount_cents - goal.saved_so_far_cents

    if remaining_cents <= 0:
        return GoalProjectionOut(
            goal_id=goal.id,
            status="already_met",
            avg_monthly_net_savings_cents=avg_monthly_net_savings_cents,
            remaining_cents=remaining_cents,
            months_to_goal=0,
            projected_date=latest_transaction_date(session, account_id),
        )

    if avg_monthly_net_savings_cents <= 0:
        # Never a negative or infinite month count -- an honest "not on track" state.
        return GoalProjectionOut(
            goal_id=goal.id,
            status="not_on_track",
            avg_monthly_net_savings_cents=avg_monthly_net_savings_cents,
            remaining_cents=remaining_cents,
            months_to_goal=None,
            projected_date=None,
        )

    months_to_goal = remaining_cents / avg_monthly_net_savings_cents
    latest = latest_transaction_date(session, account_id)
    return GoalProjectionOut(
        goal_id=goal.id,
        status="on_track",
        avg_monthly_net_savings_cents=avg_monthly_net_savings_cents,
        remaining_cents=remaining_cents,
        months_to_goal=months_to_goal,
        projected_date=_add_months(latest, months_to_goal) if latest else None,
    )


def project_goal_timeline(
    session: Session, goal: SavingsGoal, months: int, account_id: int | None
) -> GoalProjectionOut:
    avg_net_savings = average_monthly_net_savings(session, months, account_id)
    return _project_goal(session, goal, avg_net_savings, account_id)


def apply_scenario_to_goal(
    session: Session,
    goal: SavingsGoal,
    extra_monthly_savings_cents: int,
    months: int,
    account_id: int | None,
) -> GoalProjectionOut:
    """Same projection as `project_goal_timeline`, but with the scenario's extra monthly
    savings added on top of actual average net savings -- spending less accelerates the goal."""
    avg_net_savings = average_monthly_net_savings(session, months, account_id) + extra_monthly_savings_cents
    return _project_goal(session, goal, avg_net_savings, account_id)
