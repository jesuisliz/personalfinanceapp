import json
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.chat import history
from app.chat.service import _cents_to_dollars, answer_question
from app.chat.tools import build_tool_schemas, dispatch_tool_call, resolve_category_id
from app.db import Base
from app.models import Account, Category, ChatConversation, ChatMessage, CurrentBalance, SavingsGoal, Transaction
from app.routers.chat import get_conversation_messages, list_conversations, rename_conversation
from app.schemas import ChatConversationUpdate, ToolCallOut

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


def make_txn(session, account_id, amount_cents, txn_date, description="txn", category_id=None, is_transfer=False):
    global _hash_counter
    _hash_counter += 1
    txn = Transaction(
        account_id=account_id,
        date=txn_date,
        description=description,
        amount_cents=amount_cents,
        category_id=category_id,
        is_transfer=is_transfer,
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


def test_dispatch_get_category_transactions_all_months_when_month_omitted():
    """Regression test: asking about a category spanning many months used to force
    one tool call per month, risking the 5-round cap on a long enough history.
    Omitting `month` entirely must return everything in one call."""
    session = make_session()
    account = make_account(session)
    loan = make_category(session, "Auto Loan")
    make_txn(session, account.id, -80000, date(2026, 1, 12), description="Loan Jan", category_id=loan.id)
    make_txn(session, account.id, -80000, date(2026, 7, 10), description="Loan Jul", category_id=loan.id)

    result = dispatch_tool_call(session, "get_category_transactions", {"category_name": "Auto Loan"})

    assert {r["description"] for r in result} == {"Loan Jan", "Loan Jul"}


def test_dispatch_get_category_transactions_uncategorized():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -1000, date(2026, 7, 1), description="Mystery")

    result = dispatch_tool_call(
        session, "get_category_transactions", {"month": "2026-07", "category_name": "Uncategorized"}
    )

    assert result == [{"date": "2026-07-01", "description": "Mystery", "amount_cents": -1000}]


def test_dispatch_get_category_transactions_for_credit_card_payment_bypasses_spending_exclusion():
    """Regression test: get_category_transactions used to always return [] for
    "Credit Card Payment"/"Transfers" because it drilled into category_breakdown's
    spending total, and those categories are deliberately excluded from that total
    entirely. It must route to a direct lookup instead for these two category names,
    including confirmed is_transfer pairs a normal category drill-down would hide."""
    session = make_session()
    account = make_account(session)
    payments = make_category(session, "Credit Card Payment")
    make_txn(
        session, account.id, -20000, date(2026, 7, 1), description="Payment to Card",
        category_id=payments.id, is_transfer=True,
    )

    result = dispatch_tool_call(
        session, "get_category_transactions", {"month": "2026-07", "category_name": "Credit Card Payment"}
    )

    assert result == [{"date": "2026-07-01", "description": "Payment to Card", "amount_cents": -20000}]


def test_dispatch_get_category_transactions_dining_still_excludes_transfers():
    """Normal spending categories must keep the existing behavior unchanged."""
    session = make_session()
    account = make_account(session)
    dining = make_category(session, "Dining & Drinks")
    make_txn(session, account.id, -1000, date(2026, 7, 1), category_id=dining.id, is_transfer=True)

    result = dispatch_tool_call(
        session, "get_category_transactions", {"month": "2026-07", "category_name": "Dining & Drinks"}
    )

    assert result == []


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
    assert result["balance_source"] == "stored"


def test_dispatch_get_financial_runway_configured():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -100000, date(2026, 7, 15))
    session.add(CurrentBalance(amount_cents=500000, updated_at=datetime(2026, 7, 27)))
    session.commit()

    result = dispatch_tool_call(session, "get_financial_runway", {"months": 1})

    assert result["balance_configured"] is True
    assert result["balance_source"] == "stored"
    assert result["runway_months"] == 5.0


def test_dispatch_get_financial_runway_hypothetical_balance_overrides_stored():
    """A user asking a one-off 'what if I had $X' question in chat should get an
    answer based on that stated amount, not their saved balance -- and the saved
    balance must be left completely untouched afterward (never an implicit write)."""
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -100000, date(2026, 7, 15))
    session.add(CurrentBalance(amount_cents=500000, updated_at=datetime(2026, 7, 27)))
    session.commit()

    result = dispatch_tool_call(
        session,
        "get_financial_runway",
        {"months": 1, "hypothetical_balance_cents": 1500000},
    )

    assert result["balance_source"] == "hypothetical"
    assert result["current_balance_cents"] == 1500000
    assert result["runway_months"] == 15.0

    stored = session.execute(select(CurrentBalance)).scalar_one()
    assert stored.amount_cents == 500000


def test_dispatch_get_financial_runway_hypothetical_balance_works_when_none_stored():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -50000, date(2026, 7, 15))

    result = dispatch_tool_call(
        session,
        "get_financial_runway",
        {"months": 1, "hypothetical_balance_cents": 300000},
    )

    assert result["balance_configured"] is True
    assert result["balance_source"] == "hypothetical"
    assert result["runway_months"] == 6.0


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


def test_cents_to_dollars_converts_nested_structure():
    # Regression test: a live question ("which categories increased") had the model
    # correctly convert some entries but print others as raw cents ("$85,824" instead of
    # $858.24) -- a 100x error. Tool results are now converted before the model ever sees
    # them, so there is nothing left for the model to get wrong.
    raw = {
        "2026-02": [{"category_id": 1, "category_name": "Dining & Drinks", "total_cents": 57740}],
        "2026-07": [{"category_id": 1, "category_name": "Dining & Drinks", "total_cents": 85824}],
    }

    converted = _cents_to_dollars(raw)

    assert converted == {
        "2026-02": [{"category_id": 1, "category_name": "Dining & Drinks", "total_dollars": 577.40}],
        "2026-07": [{"category_id": 1, "category_name": "Dining & Drinks", "total_dollars": 858.24}],
    }


def test_cents_to_dollars_leaves_non_cents_fields_alone():
    raw = {"category_id": 1, "amount_cents": -1050, "nested": {"months_considered": 6}}

    assert _cents_to_dollars(raw) == {
        "category_id": 1,
        "amount_dollars": -10.50,
        "nested": {"months_considered": 6},
    }


# --- Phase 6 M1: chat history persistence ---


def test_answer_question_persists_one_conversation_and_two_messages():
    session = make_session()
    client = FakeClient([FakeResponse(FakeMessage(content="Hello there!"))])

    result = answer_question(session, "hi", history=[], client=client)

    conversations = session.execute(select(ChatConversation)).scalars().all()
    assert len(conversations) == 1
    assert conversations[0].id == result.conversation_id
    assert conversations[0].title == "hi"

    messages = session.execute(select(ChatMessage)).scalars().all()
    assert [(m.role, m.content) for m in messages] == [("user", "hi"), ("assistant", "Hello there!")]
    assert all(m.conversation_id == result.conversation_id for m in messages)
    assert messages[1].tool_calls_json is None


def test_answer_question_persists_tool_calls_on_assistant_message():
    session = make_session()
    account = make_account(session)
    make_txn(session, account.id, -5000, date(2026, 7, 15))

    tool_call = FakeToolCall("call_1", "get_monthly_summary", json.dumps({"months": 1}))
    responses = [
        FakeResponse(FakeMessage(content=None, tool_calls=[tool_call])),
        FakeResponse(FakeMessage(content="You spent $50 in July.")),
    ]
    client = FakeClient(responses)

    answer_question(session, "how much did I spend?", history=[], client=client)

    assistant_message = session.execute(
        select(ChatMessage).where(ChatMessage.role == "assistant")
    ).scalar_one()
    stored_tool_calls = json.loads(assistant_message.tool_calls_json)
    assert len(stored_tool_calls) == 1
    assert stored_tool_calls[0]["name"] == "get_monthly_summary"


def test_answer_question_reuses_conversation_when_id_passed():
    session = make_session()
    first_client = FakeClient([FakeResponse(FakeMessage(content="First reply"))])
    first_result = answer_question(session, "first message", history=[], client=first_client)

    second_client = FakeClient([FakeResponse(FakeMessage(content="Second reply"))])
    second_result = answer_question(
        session, "second message", history=[], client=second_client, conversation_id=first_result.conversation_id
    )

    assert second_result.conversation_id == first_result.conversation_id
    assert len(session.execute(select(ChatConversation)).scalars().all()) == 1
    assert len(session.execute(select(ChatMessage)).scalars().all()) == 4


def test_answer_question_unknown_conversation_id_raises():
    session = make_session()
    client = FakeClient([FakeResponse(FakeMessage(content="Hello there!"))])

    with pytest.raises(ValueError):
        answer_question(session, "hi", history=[], client=client, conversation_id=999)


# --- Phase 6 M2: GET /chat/conversations/{id}/messages ---


def test_get_conversation_messages_returns_in_order_with_tool_calls():
    session = make_session()
    conversation = history.create_conversation(session, "how much did I spend?")
    history.append_message(session, conversation.id, "user", "how much did I spend?")
    tool_call = ToolCallOut(name="get_monthly_summary", arguments={"months": 1}, result={"expense_cents": 5000})
    history.append_message(session, conversation.id, "assistant", "You spent $50.", tool_calls=[tool_call])

    result = get_conversation_messages(conversation.id, db=session)

    assert [m.role for m in result] == ["user", "assistant"]
    assert result[0].tool_calls == []
    assert result[1].tool_calls == [tool_call]


def test_get_conversation_messages_unknown_id_returns_404():
    session = make_session()

    with pytest.raises(HTTPException) as exc_info:
        get_conversation_messages(999, db=session)

    assert exc_info.value.status_code == 404


# --- Phase 6 M3: GET /chat/conversations ---


def test_list_conversations_ordered_by_most_recently_updated():
    session = make_session()
    older = history.create_conversation(session, "first conversation")
    newer = history.create_conversation(session, "second conversation")
    # Touch the older one again so it becomes the most recently updated.
    history.append_message(session, older.id, "user", "another message")

    result = list_conversations(db=session)

    assert [c.id for c in result] == [older.id, newer.id]
    assert result[0].title == "first conversation"


def test_list_conversations_empty_when_none_exist():
    session = make_session()

    assert list_conversations(db=session) == []


# --- Phase 6 M4: PATCH /chat/conversations/{id} ---


def test_history_rename_conversation_updates_title():
    session = make_session()
    conversation = history.create_conversation(session, "original title")

    renamed = history.rename_conversation(session, conversation.id, "new title")

    assert renamed.title == "new title"
    assert session.get(ChatConversation, conversation.id).title == "new title"


def test_rename_conversation_router_updates_title():
    session = make_session()
    conversation = history.create_conversation(session, "original title")

    result = rename_conversation(conversation.id, ChatConversationUpdate(title="new title"), db=session)

    assert result.title == "new title"


def test_rename_conversation_unknown_id_returns_404():
    session = make_session()

    with pytest.raises(HTTPException) as exc_info:
        rename_conversation(999, ChatConversationUpdate(title="new title"), db=session)

    assert exc_info.value.status_code == 404
