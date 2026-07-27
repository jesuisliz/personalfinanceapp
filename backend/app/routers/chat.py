from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.chat.service import answer_question
from app.db import get_db
from app.schemas import ChatReplyOut, ChatRequestIn

router = APIRouter()


@router.post("/chat", response_model=ChatReplyOut)
def chat(body: ChatRequestIn, db: Session = Depends(get_db)):
    try:
        return answer_question(db, body.message, body.history)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
