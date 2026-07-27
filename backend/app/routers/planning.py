from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.tools import UNCATEGORIZED_NAME, resolve_category_id
from app.dashboard.aggregates import estimate_category_reduction_savings
from app.db import get_db
from app.models import CurrentBalance, SavingsGoal
from app.planning.aggregates import (
    apply_scenario_to_goal,
    apply_scenario_to_runway,
    compute_runway,
    get_current_balance_cents,
    project_goal_timeline,
)
from app.schemas import (
    CurrentBalanceOut,
    CurrentBalanceUpdate,
    GoalProjectionOut,
    RunwayOut,
    SavingsGoalCreate,
    SavingsGoalOut,
    SavingsGoalUpdate,
    ScenarioOut,
    ScenarioRequestIn,
)

router = APIRouter()


@router.get("/goals", response_model=list[SavingsGoalOut])
def list_goals(db: Session = Depends(get_db)):
    return db.execute(select(SavingsGoal)).scalars().all()


@router.post("/goals", response_model=SavingsGoalOut)
def create_goal(body: SavingsGoalCreate, db: Session = Depends(get_db)):
    goal = SavingsGoal(**body.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.patch("/goals/{goal_id}", response_model=SavingsGoalOut)
def update_goal(goal_id: int, body: SavingsGoalUpdate, db: Session = Depends(get_db)):
    goal = db.get(SavingsGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    goal = db.get(SavingsGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    db.delete(goal)
    db.commit()


@router.get("/goals/{goal_id}/projection", response_model=GoalProjectionOut)
def get_goal_projection(
    goal_id: int, months: int = 6, account_id: int | None = None, db: Session = Depends(get_db)
):
    goal = db.get(SavingsGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return project_goal_timeline(db, goal, months, account_id)


def _get_balance_row(db: Session) -> CurrentBalance | None:
    return db.execute(select(CurrentBalance)).scalars().first()


@router.get("/balance", response_model=CurrentBalanceOut)
def get_balance(db: Session = Depends(get_db)):
    row = _get_balance_row(db)
    if row is None:
        return CurrentBalanceOut(configured=False, amount_cents=None, updated_at=None)
    return CurrentBalanceOut(configured=True, amount_cents=row.amount_cents, updated_at=row.updated_at)


@router.put("/balance", response_model=CurrentBalanceOut)
def set_balance(body: CurrentBalanceUpdate, db: Session = Depends(get_db)):
    row = _get_balance_row(db)
    now = datetime.now()
    if row is None:
        row = CurrentBalance(amount_cents=body.amount_cents, updated_at=now)
        db.add(row)
    else:
        row.amount_cents = body.amount_cents
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return CurrentBalanceOut(configured=True, amount_cents=row.amount_cents, updated_at=row.updated_at)


@router.get("/runway", response_model=RunwayOut)
def get_runway(months: int = 6, account_id: int | None = None, db: Session = Depends(get_db)):
    return compute_runway(db, get_current_balance_cents(db), months, account_id)


@router.post("/scenario", response_model=ScenarioOut)
def run_scenario(body: ScenarioRequestIn, db: Session = Depends(get_db)):
    uncategorized = body.category_name == UNCATEGORIZED_NAME
    try:
        category_id = resolve_category_id(db, body.category_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    estimate = estimate_category_reduction_savings(
        db, category_id, uncategorized, body.reduction_percent, body.months, body.account_id
    )

    runway = None
    goal_projection = None

    if body.goal_id is not None:
        goal = db.get(SavingsGoal, body.goal_id)
        if goal is None:
            raise HTTPException(status_code=404, detail=f"Goal {body.goal_id} not found")
        goal_projection = apply_scenario_to_goal(
            db, goal, estimate.monthly_savings_cents, body.months, body.account_id
        )
    else:
        runway = apply_scenario_to_runway(
            db, get_current_balance_cents(db), estimate.monthly_savings_cents, body.months, body.account_id
        )

    return ScenarioOut(savings_estimate=estimate, runway=runway, goal_projection=goal_projection)
