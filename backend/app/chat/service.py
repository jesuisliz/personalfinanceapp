import json

from openai import OpenAI
from sqlalchemy.orm import Session

from app.chat.tools import build_tool_schemas, dispatch_tool_call
from app.config import OPENAI_API_KEY
from app.schemas import ChatMessageIn, ChatReplyOut, ToolCallOut

MODEL = "gpt-4o-mini"
MAX_TOOL_ROUNDS = 5
MAX_HISTORY_MESSAGES = 20

SYSTEM_PROMPT = (
    "You are a financial assistant for a personal finance app. You have tools that query "
    "the user's real transaction data. Never sum, average, estimate, or otherwise calculate "
    "a financial total yourself -- always call a tool for any numeric aggregation. You may "
    "describe or compare numbers a tool has already returned. All amounts from tools are in "
    "cents; convert to dollars when describing them. Be concise and direct."
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

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
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
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    return ChatReplyOut(
        reply=(
            "I wasn't able to finish answering that within the allowed number of steps. "
            "Try asking a more specific question."
        ),
        tool_calls=tool_calls_made,
    )
