import json

from openai import OpenAI
from sqlalchemy.orm import Session

from app.chat.tools import build_tool_schemas, dispatch_tool_call
from app.config import OPENAI_API_KEY
from app.dashboard.aggregates import latest_transaction_date
from app.schemas import ChatMessageIn, ChatReplyOut, ToolCallOut

MODEL = "gpt-4o-mini"
MAX_TOOL_ROUNDS = 5
MAX_HISTORY_MESSAGES = 20

BASE_SYSTEM_PROMPT = (
    "You are a financial assistant for a personal finance app. You have tools that query "
    "the user's real transaction data. Never sum, average, estimate, or otherwise calculate "
    "a financial total yourself -- always call a tool for any numeric aggregation. You may "
    "describe or compare numbers a tool has already returned. Every dollar amount a tool "
    "returns is already in dollars -- read it as-is, never rescale or reinterpret it. Be "
    "concise and direct."
)


def _cents_to_dollars(value):
    """Recursively rewrite every '*_cents' key/value as a '*_dollars' float.

    The model is unreliable at mentally rescaling raw cents integers (confirmed live: it
    correctly converted some entries but printed others as if cents were dollars, a 100x
    error). Rather than depend on prompt-followed arithmetic, dollars are the only unit the
    model ever sees. The frontend's own tool-call rendering is unaffected -- it reads the
    original cents-based ToolCallOut.result, not this converted copy.
    """
    if isinstance(value, dict):
        converted = {}
        for key, val in value.items():
            if key.endswith("_cents") and isinstance(val, (int, float)):
                converted[key[: -len("_cents")] + "_dollars"] = round(val / 100, 2)
            else:
                converted[key] = _cents_to_dollars(val)
        return converted
    if isinstance(value, list):
        return [_cents_to_dollars(v) for v in value]
    return value


def _system_prompt(session: Session) -> str:
    latest = latest_transaction_date(session, account_id=None)
    if latest is None:
        return BASE_SYSTEM_PROMPT
    return (
        f"{BASE_SYSTEM_PROMPT} The most recent transaction in the data is dated {latest.isoformat()} "
        f"-- treat that as \"today\" when resolving relative phrases like \"this month\" or \"last "
        "month\" into a YYYY-MM value for tool calls. Do not use your own training date."
    )


def _default_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured. Add it to backend/.env.")
    return OpenAI(api_key=OPENAI_API_KEY)


def answer_question(
    session: Session,
    message: str,
    history: list[ChatMessageIn],
    client: OpenAI | None = None,
) -> ChatReplyOut:
    client = client or _default_client()
    tool_schemas = build_tool_schemas(session)

    messages: list[dict] = [{"role": "system", "content": _system_prompt(session)}]
    messages += [{"role": h.role, "content": h.content} for h in history[-MAX_HISTORY_MESSAGES:]]
    messages.append({"role": "user", "content": message})

    tool_calls_made: list[ToolCallOut] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tool_schemas)
        choice_message = response.choices[0].message

        if not choice_message.tool_calls:
            return ChatReplyOut(reply=choice_message.content or "", tool_calls=tool_calls_made)

        messages.append(
            {
                "role": "assistant",
                "content": choice_message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in choice_message.tool_calls
                ],
            }
        )

        for tc in choice_message.tool_calls:
            arguments = json.loads(tc.function.arguments)
            try:
                result = dispatch_tool_call(session, tc.function.name, arguments)
            except Exception as exc:
                result = {"error": str(exc)}

            tool_calls_made.append(ToolCallOut(name=tc.function.name, arguments=arguments, result=result))
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(_cents_to_dollars(result))}
            )

    return ChatReplyOut(
        reply=(
            "I wasn't able to finish answering that within the allowed number of steps. "
            "Try asking a more specific question."
        ),
        tool_calls=tool_calls_made,
    )
