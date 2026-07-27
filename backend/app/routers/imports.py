from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.imports.pipeline import import_file
from app.schemas import ImportSummaryOut

router = APIRouter()


@router.post("/imports", response_model=ImportSummaryOut)
async def create_import(file: UploadFile, db: Session = Depends(get_db)):
    file_bytes = await file.read()
    try:
        summary = import_file(db, file.filename, file_bytes)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return summary
