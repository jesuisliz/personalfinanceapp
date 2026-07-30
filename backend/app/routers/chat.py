import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.chat import history
from app.chat.service import answer_question
from app.db import get_db
from app.models import ChatConversation
from app.schemas import (
    ChatConversationOut,
    ChatConversationUpdate,
    ChatMessageOut,
    ChatReplyOut,
    ChatRequestIn,
    ToolCallOut,
)

router = APIRouter()


@router.post("/chat", response_model=ChatReplyOut)
def chat(body: ChatRequestIn, db: Session = Depends(get_db)):
    try:
        return answer_question(db, body.message, body.history, conversation_id=body.conversation_id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/chat/conversations", response_model=list[ChatConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    return history.list_conversations(db)


@router.get("/chat/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
def get_conversation_messages(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.get(ChatConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

    return [
        ChatMessageOut(
            role=message.role,
            content=message.content,
            tool_calls=[ToolCallOut(**tc) for tc in json.loads(message.tool_calls_json)]
            if message.tool_calls_json
            else [],
        )
        for message in history.get_conversation_messages(db, conversation_id)
    ]


@router.patch("/chat/conversations/{conversation_id}", response_model=ChatConversationOut)
def rename_conversation(conversation_id: int, body: ChatConversationUpdate, db: Session = Depends(get_db)):
    conversation = db.get(ChatConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")

    return history.rename_conversation(db, conversation_id, body.title)
