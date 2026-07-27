import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.chat.service import answer_question
from app.chat.tools import build_tool_schemas, dispatch_tool_call, resolve_category_id
from app.db import Base
from app.models import Account, Category, CurrentBalance, SavingsGoal, Transaction

# --- fixtures / helpers (mirrors the pattern in test_dashboard.py) ---


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


def make_txn(session, account_id, amount_cents, txn_date, description="txn", category_id=None):
    global _hash_counter
    _hash_counter += 1
    txn = Transaction(
        account_id=account_id,
        date=txn_date,
        description=description,
        amount_cents=amount_cents,
        category_id=category_id,
        source_row_hash=f"hash-{_hash_counter}",
    )
    session.add(txn)
    session.commit()
    return txn


# --- fake OpenAI client, no network/real API involved ---


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeResponse:
    def __init__(self, message):
        self.choices = [type("Choice", (), {"message": message})()]


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.chat = type("Chat", (), {"completions": FakeCompletions(responses)})()


# --- resolve_category_id ---


def test_resolve_category_id_uncategorized_special_case():
    session = make_session()
    assert resolve_category_id(session, "Uncategorized") is None


def test_resolve_category_id_found():
    session = make_session()
    dining = make_category(session, "Dining & Drinks")
    assert resolve_category_id(session, "Dining & Drinks") == dining.id


def test_resolve_category_id_unknown_raises():
    session = make_session()
    with pytest.raises(ValueError):
        resolve_category_id(session, "Not A Real Category")


# --- build_tool_schemas ---


def test_build_tool_schemas_enum_reflects_current_categories():
    session = make_session()
    make_category(session, "Dining & Drinks")
    schemas = build_tool_schemas(session)

    txn_schema = next(s for s in schemas if s["function"]["name"] == "get_category_transactions")
    enum_values = txn_schema["function"]["parameters"]["properties"]["category_name"]["enum"]

    assert "Dining & Drinks" in enum_values
    assert "Uncategorized" in enum_values


# --- dispatch_tool_call ---


def test_dispatch_get_monthly_summary():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -1000, date(2026, 7, 1))

    result = dispatch_tool_call(session, "get_monthly_summary", {"months": 1})

    assert result == [{"month": "2026-07", "income_cents": 0, "expense_cents": 1000, "net_cents": -1000}]


def test_dispatch_get_category_breakdown():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=dining.id)

    result = dispatch_tool_call(session, "get_category_breakdown", {"month": "2026-07"})

    assert result == [{"category_id": dining.id, "category_name": "Dining & Drinks", "total_cents": 1000}]


def test_dispatch_get_top_merchants():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -1000, date(2026, 7, 1), description="Cafe")

    result = dispatch_tool_call(session, "get_top_merchants", {"month": "2026-07"})

    assert result == [{"merchant": "Cafe", "total_cents": 1000, "transaction_count": 1}]


def test_dispatch_get_category_transactions():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -1000, date(2026, 7, 1), description="Olive Garden", category_id=dining.id)

    result = dispatch_tool_call(
        session, "get_category_transactions", {"month": "2026-07", "category_name": "Dining & Drinks"}
    )

    assert result == [{"date": "2026-07-01", "description": "Olive Garden", "amount_cents": -1000}]


def test_dispatch_get_category_transactions_uncategorized():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -1000, date(2026, 7, 1), description="Mystery")

    result = dispatch_tool_call(
        session, "get_category_transactions", {"month": "2026-07", "category_name": "Uncategorized"}
    )

    assert result == [{"date": "2026-07-01", "description": "Mystery", "amount_cents": -1000}]


def test_dispatch_get_category_trends():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=dining.id)

    result = dispatch_tool_call(session, "get_category_trends", {"months": 1})

    assert result == {"2026-07": [{"category_id": dining.id, "category_name": "Dining & Drinks", "total_cents": 1000}]}


def test_dispatch_estimate_category_reduction_savings():
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -10000, date(2026, 7, 1), category_id=dining.id)

    result = dispatch_tool_call(
        session,
        "estimate_category_reduction_savings",
        {"category_name": "Dining & Drinks", "reduction_percent": 50, "months": 1},
    )

    assert result == {
        "avg_monthly_cents": 10000,
        "monthly_savings_cents": 5000,
        "annual_savings_cents": 60000,
        "months_considered": 1,
    }


def test_dispatch_unknown_tool_raises():
    session = make_session()
    with pytest.raises(ValueError):
        dispatch_tool_call(session, "not_a_real_tool", {})


def test_dispatch_unknown_category_raises():
    session = make_session()
    with pytest.raises(ValueError):
        dispatch_tool_call(
            session, "get_category_transactions", {"month": "2026-07", "category_name": "Not Real"}
        )


def test_dispatch_get_savings_goals_includes_projection():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, 50000, date(2026, 7, 1))  # net savings $500/mo
    goal = SavingsGoal(name="Vacation", target_amount_cents=200000, saved_so_far_cents=0)
    session.add(goal)
    session.commit()

    result = dispatch_tool_call(session, "get_savings_goals", {"months": 1})

    assert len(result) == 1
    assert result[0]["name"] == "Vacation"
    assert result[0]["projection"]["status"] == "on_track"
    assert result[0]["projection"]["months_to_goal"] == 4.0


def test_dispatch_get_financial_runway_not_configured():
    session = make_session()
    result = dispatch_tool_call(session, "get_financial_runway", {"months": 6})
    assert result["balance_configured"] is False


def test_dispatch_get_financial_runway_configured():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -100000, date(2026, 7, 15))
    session.add(CurrentBalance(amount_cents=500000, updated_at=datetime(2026, 7, 27)))
    session.commit()

    result = dispatch_tool_call(session, "get_financial_runway", {"months": 1})

    assert result["balance_configured"] is True
    assert result["runway_months"] == 5.0


# --- answer_question orchestration loop (fake client, no network/API key needed) ---


def test_answer_question_no_tool_call_returns_reply_directly():
    session = make_session()
    client = FakeClient([FakeResponse(FakeMessage(content="Hello there!"))])

    result = answer_question(session, "hi", history=[], client=client)

    assert result.reply == "Hello there!"
    assert result.tool_calls == []


def test_answer_question_executes_tool_call_against_real_data_then_replies():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -5000, date(2026, 7, 15))

    tool_call = FakeToolCall("call_1", "get_monthly_summary", json.dumps({"months": 1}))
    responses = [
        FakeResponse(FakeMessage(content=None, tool_calls=[tool_call])),
        FakeResponse(FakeMessage(content="You spent $50 in July.")),
    ]
    client = FakeClient(responses)

    result = answer_question(session, "how much did I spend?", history=[], client=client)

    assert result.reply == "You spent $50 in July."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_monthly_summary"
    assert result.tool_calls[0].result[0]["expense_cents"] == 5000


def test_answer_question_tool_error_is_surfaced_not_crashed():
    session = make_session()
    tool_call = FakeToolCall(
        "call_1", "get_category_transactions", json.dumps({"month": "2026-07", "category_name": "Not Real"})
    )
    responses = [
        FakeResponse(FakeMessage(content=None, tool_calls=[tool_call])),
        FakeResponse(FakeMessage(content="I couldn't find that category.")),
    ]
    client = FakeClient(responses)

    result = answer_question(session, "how much on Not Real?", history=[], client=client)

    assert result.tool_calls[0].result == {"error": "Unknown category: 'Not Real'"}
    assert result.reply == "I couldn't find that category."


def test_answer_question_respects_max_tool_rounds():
    session = make_session()
    tool_call = FakeToolCall("call_x", "get_monthly_summary", json.dumps({"months": 1}))
    # Always returns another tool call, never a final answer -- should not loop forever.
    responses = [FakeResponse(FakeMessage(content=None, tool_calls=[tool_call])) for _ in range(10)]
    client = FakeClient(responses)

    result = answer_question(session, "loop forever", history=[], client=client)

    assert "allowed number of steps" in result.reply
