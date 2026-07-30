import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatConversation, ChatMessage
from app.schemas import ToolCallOut

TITLE_MAX_LENGTH = 60


def create_conversation(session: Session, first_message: str) -> ChatConversation:
    now = datetime.now()
    conversation = ChatConversation(title=first_message.strip()[:TITLE_MAX_LENGTH], created_at=now, updated_at=now)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def append_message(
    session: Session,
    conversation_id: int,
    role: str,
    content: str,
    tool_calls: list[ToolCallOut] | None = None,
) -> ChatMessage:
    now = datetime.now()
    message = ChatMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_calls_json=json.dumps([tc.model_dump() for tc in tool_calls]) if tool_calls else None,
        created_at=now,
    )
    session.add(message)

    conversation = session.get(ChatConversation, conversation_id)
    conversation.updated_at = now

    session.commit()
    session.refresh(message)
    return message


def get_conversation_messages(session: Session, conversation_id: int) -> list[ChatMessage]:
    return list(
        session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc())
        ).scalars()
    )


def list_conversations(session: Session) -> list[ChatConversation]:
    return list(session.execute(select(ChatConversation).order_by(ChatConversation.updated_at.desc())).scalars())


def rename_conversation(session: Session, conversation_id: int, title: str) -> ChatConversation:
    conversation = session.get(ChatConversation, conversation_id)
    conversation.title = title
    session.commit()
    session.refresh(conversation)
    return conversation
