from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dashboard.aggregates import (
    NON_SPENDING_CATEGORY_NAMES,
    category_breakdown,
    category_transactions,
    category_trends,
    estimate_category_reduction_savings,
    monthly_summary,
    non_spending_category_transactions,
    top_merchants,
)
from app.models import Category, SavingsGoal
from app.planning.aggregates import compute_runway, get_current_balance_cents, project_goal_timeline

UNCATEGORIZED_NAME = "Uncategorized"


def resolve_category_id(session: Session, category_name: str) -> int | None:
    """Exact-name lookup. 'Uncategorized' is a reserved value meaning category_id IS NULL.
    Raises for anything else unrecognized -- never guessed against a similar-sounding name."""
    if category_name == UNCATEGORIZED_NAME:
        return None
    category = session.execute(select(Category).where(Category.name == category_name)).scalar_one_or_none()
    if category is None:
        raise ValueError(f"Unknown category: {category_name!r}")
    return category.id


def category_name_enum(session: Session) -> list[str]:
    names = sorted(c.name for c in session.execute(select(Category)).scalars().all())
    return [*names, UNCATEGORIZED_NAME]


def build_tool_schemas(session: Session) -> list[dict]:
    category_names = category_name_enum(session)
    return [
        {
            "type": "function",
            "function": {
                "name": "get_monthly_summary",
                "description": "Income, expenses, and net savings for each of the trailing N calendar months.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "months": {"type": "integer", "description": "How many trailing months, e.g. 6"},
                        "account_id": {
                            "type": ["integer", "null"],
                            "description": "Optional: scope to one account instead of all accounts",
                        },
                    },
                    "required": ["months"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_category_breakdown",
                "description": "Spending broken down by category for a single calendar month.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "month": {"type": "string", "description": "Calendar month as YYYY-MM"},
                        "account_id": {"type": ["integer", "null"]},
                    },
                    "required": ["month"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_top_merchants",
                "description": "Top merchants by amount spent for a single calendar month.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "month": {"type": "string", "description": "Calendar month as YYYY-MM"},
                        "account_id": {"type": ["integer", "null"]},
                        "limit": {"type": "integer", "description": "Max merchants to return, default 10"},
                    },
                    "required": ["month"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_category_transactions",
                "description": (
                    "The individual transactions in one category. Pass `month` for a single "
                    "calendar month, or omit it entirely to get every transaction in that "
                    "category across all time in one call - do this whenever the question spans "
                    "multiple months or 'all months', rather than calling this once per month."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "month": {
                            "type": ["string", "null"],
                            "description": "Calendar month as YYYY-MM, or omit/null for all-time",
                        },
                        "category_name": {"type": "string", "enum": category_names},
                        "account_id": {"type": ["integer", "null"]},
                    },
                    "required": ["category_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_category_trends",
                "description": (
                    "Full category breakdown for each of the trailing N months, to see which "
                    "categories rose or fell over time."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "months": {"type": "integer", "description": "How many trailing months, e.g. 6"},
                        "account_id": {"type": ["integer", "null"]},
                    },
                    "required": ["months"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "estimate_category_reduction_savings",
                "description": (
                    "Estimate monthly and annual savings from reducing spend in one category by a "
                    "percentage, based on that category's actual average spend over the trailing N months."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category_name": {"type": "string", "enum": category_names},
                        "reduction_percent": {"type": "number", "description": "e.g. 25 for a 25% reduction"},
                        "months": {"type": "integer", "description": "Trailing months to average over, e.g. 6"},
                        "account_id": {"type": ["integer", "null"]},
                    },
                    "required": ["category_name", "reduction_percent", "months"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_savings_goals",
                "description": (
                    "List all savings goals (including vacations -- a vacation is just a goal) "
                    "with their target amount, amount saved so far, and a projected timeline based "
                    "on the user's actual average monthly net savings."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "months": {
                            "type": "integer",
                            "description": "Trailing months to average net savings over, e.g. 6",
                        },
                        "account_id": {"type": ["integer", "null"]},
                    },
                    "required": ["months"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_financial_runway",
                "description": (
                    "How many months the user's current savings would last at their actual average "
                    "monthly expense rate (e.g. if they left their job). Uses the user's saved current "
                    "balance by default -- if they haven't entered one, this returns "
                    "balance_configured=false rather than a number. If the user instead poses a "
                    "hypothetical in conversation (e.g. 'let's say I have $15,000'), pass that amount "
                    "as hypothetical_balance_cents to simulate it without touching their saved balance."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "months": {
                            "type": "integer",
                            "description": "Trailing months to average expenses over, e.g. 6",
                        },
                        "account_id": {"type": ["integer", "null"]},
                        "hypothetical_balance_cents": {
                            "type": ["integer", "null"],
                            "description": (
                                "A one-off balance stated in conversation, in cents, to simulate "
                                "instead of the user's saved balance. Never persisted. Omit/null to "
                                "use the user's actually-saved balance instead."
                            ),
                        },
                    },
                    "required": ["months"],
                },
            },
        },
    ]


def dispatch_tool_call(session: Session, name: str, arguments: dict) -> dict | list:
    account_id = arguments.get("account_id")

    if name == "get_monthly_summary":
        return [r.model_dump() for r in monthly_summary(session, arguments["months"], account_id)]

    if name == "get_category_breakdown":
        return [r.model_dump() for r in category_breakdown(session, arguments["month"], account_id)]

    if name == "get_top_merchants":
        limit = arguments.get("limit", 10)
        return [r.model_dump() for r in top_merchants(session, arguments["month"], account_id, limit)]

    if name == "get_category_transactions":
        category_name = arguments["category_name"]
        uncategorized = category_name == UNCATEGORIZED_NAME
        category_id = resolve_category_id(session, category_name)
        month = arguments.get("month")
        if category_name in NON_SPENDING_CATEGORY_NAMES:
            rows = non_spending_category_transactions(session, month, account_id, category_id)
        else:
            rows = category_transactions(session, month, account_id, category_id, uncategorized)
        return [
            {
                "date": t.date.isoformat(),
                "description": t.clean_description or t.description,
                "amount_cents": t.amount_cents,
            }
            for t in rows
        ]

    if name == "get_category_trends":
        trends = category_trends(session, arguments["months"], account_id)
        return {month: [r.model_dump() for r in rows] for month, rows in trends.items()}

    if name == "estimate_category_reduction_savings":
        category_name = arguments["category_name"]
        uncategorized = category_name == UNCATEGORIZED_NAME
        category_id = resolve_category_id(session, category_name)
        result = estimate_category_reduction_savings(
            session,
            category_id,
            uncategorized,
            arguments["reduction_percent"],
            arguments["months"],
            account_id,
        )
        return result.model_dump()

    if name == "get_savings_goals":
        goals = session.execute(select(SavingsGoal)).scalars().all()
        return [
            {
                "id": g.id,
                "name": g.name,
                "target_amount_cents": g.target_amount_cents,
                "target_date": g.target_date.isoformat() if g.target_date else None,
                "saved_so_far_cents": g.saved_so_far_cents,
                "projection": project_goal_timeline(session, g, arguments["months"], account_id).model_dump(
                    mode="json"
                ),
            }
            for g in goals
        ]

    if name == "get_financial_runway":
        hypothetical_balance_cents = arguments.get("hypothetical_balance_cents")
        if hypothetical_balance_cents is not None:
            balance_cents = hypothetical_balance_cents
            balance_source = "hypothetical"
        else:
            balance_cents = get_current_balance_cents(session)
            balance_source = "stored"
        result = compute_runway(session, balance_cents, arguments["months"], account_id)
        return {"balance_source": balance_source, **result.model_dump(mode="json")}

    raise ValueError(f"Unknown tool: {name!r}")
