from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    institution: str
    account_type: str


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    date: date
    posted_date: date | None
    description: str
    amount_cents: int
    raw_category: str | None
    memo: str | None
    category_id: int | None
    clean_description: str | None
    is_transfer: bool
    note: str | None


class TransactionUpdate(BaseModel):
    category_id: int | None = None
    clean_description: str | None = None
    is_transfer: bool | None = None
    note: str | None = None


class ImportSummaryOut(BaseModel):
    filename: str
    rows_seen: int
    rows_inserted: int
    rows_skipped_as_duplicate: int


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None


class CategoryCreate(BaseModel):
    name: str
    parent_id: int | None = None


class CategoryUpdate(BaseModel):
    name: str


class MerchantRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    match_pattern: str
    clean_name: str
    category_id: int | None


class MerchantRuleCreate(BaseModel):
    match_pattern: str
    clean_name: str
    category_id: int | None = None


class TransferMatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id_a: int
    transaction_id_b: int
    status: str


class TransferMatchUpdate(BaseModel):
    status: str


class MonthlySummaryOut(BaseModel):
    month: str
    income_cents: int
    expense_cents: int
    net_cents: int


class CategoryBreakdownOut(BaseModel):
    category_id: int | None
    category_name: str
    total_cents: int


class MerchantBreakdownOut(BaseModel):
    merchant: str
    total_cents: int
    transaction_count: int


class SavingsEstimateOut(BaseModel):
    avg_monthly_cents: int
    monthly_savings_cents: int
    annual_savings_cents: int
    months_considered: int


class ChatMessageIn(BaseModel):
    role: str
    content: str


class ChatRequestIn(BaseModel):
    message: str
    history: list[ChatMessageIn] = []


class ToolCallOut(BaseModel):
    name: str
    arguments: dict
    result: dict | list


class ChatReplyOut(BaseModel):
    reply: str
    tool_calls: list[ToolCallOut]


class SavingsGoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_amount_cents: int
    target_date: date | None
    saved_so_far_cents: int


class SavingsGoalCreate(BaseModel):
    name: str
    target_amount_cents: int
    target_date: date | None = None
    saved_so_far_cents: int = 0


class SavingsGoalUpdate(BaseModel):
    name: str | None = None
    target_amount_cents: int | None = None
    target_date: date | None = None
    saved_so_far_cents: int | None = None


class CurrentBalanceOut(BaseModel):
    configured: bool
    amount_cents: int | None
    updated_at: datetime | None


class CurrentBalanceUpdate(BaseModel):
    amount_cents: int


class RunwayOut(BaseModel):
    balance_configured: bool
    current_balance_cents: int | None
    avg_monthly_expense_cents: int
    runway_months: float | None
    projected_end_date: date | None


class GoalProjectionOut(BaseModel):
    goal_id: int
    status: str  # "on_track" | "not_on_track" | "already_met"
    avg_monthly_net_savings_cents: int
    remaining_cents: int
    months_to_goal: float | None
    projected_date: date | None


class ScenarioOut(BaseModel):
    savings_estimate: SavingsEstimateOut
    runway: RunwayOut | None = None
    goal_projection: GoalProjectionOut | None = None


class ScenarioRequestIn(BaseModel):
    category_name: str
    reduction_percent: float
    months: int
    goal_id: int | None = None
    account_id: int | None = None
