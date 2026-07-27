from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import TransferMatch
from app.schemas import TransferMatchOut, TransferMatchUpdate
from app.transfers.detect import confirm_match, detect_transfers

router = APIRouter()

VALID_STATUSES = {"suggested", "confirmed", "rejected"}


@router.post("/transfer-matches/detect", response_model=list[TransferMatchOut])
def run_detection(db: Session = Depends(get_db)):
    return detect_transfers(db)


@router.get("/transfer-matches", response_model=list[TransferMatchOut])
def list_transfer_matches(status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(TransferMatch)
    if status is not None:
        stmt = stmt.where(TransferMatch.status == status)
    return db.execute(stmt).scalars().all()


@router.patch("/transfer-matches/{match_id}", response_model=TransferMatchOut)
def update_transfer_match(match_id: int, body: TransferMatchUpdate, db: Session = Depends(get_db)):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status!r}")

    match = db.get(TransferMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Transfer match {match_id} not found")

    if body.status == "confirmed":
        confirm_match(db, match)
    else:
        match.status = body.status
        db.commit()

    db.refresh(match)
    return match
