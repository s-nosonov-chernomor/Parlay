# app/api/v1/routes_ui.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_ui import UiPageOut, UiElementOut
from app.db.ui_crud import load_ui_page

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/pages/{page}", response_model=UiPageOut)
def get_ui_page(page: str, db: Session = Depends(get_db)):
    elements, subscribe_topics = load_ui_page(db, page)
    return UiPageOut(
        page=page,
        elements=[UiElementOut(**e) for e in elements],
        subscribe_topics=subscribe_topics,
    )
