# app/api/v1/routes_ui_mode.py
from __future__ import annotations

from datetime import timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_ui_mode import UiModeSetIn, UiModeSetOut
from app.db.ui_state_crud import ensure_ui_exists, upsert_ui_state
from app.db.ui_compute import compute_hw_flags
from app.sse.hub import hub, UiStateChange

router = APIRouter(prefix="/ui", tags=["ui"])

_ALLOWED = {"WEB", "AUTO", "PRIVA", "MANUAL"}


@router.post("/{ui_id}/mode", response_model=UiModeSetOut)
def set_mode(ui_id: str, payload: UiModeSetIn, db: Session = Depends(get_db)):
    mode = payload.mode_requested.strip().upper()

    if mode not in _ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=f"mode_requested must be one of: {sorted(_ALLOWED)}",
        )

    if mode == "AUTO" and not payload.schedule_id:
        raise HTTPException(
            status_code=400,
            detail="schedule_id is required for AUTO",
        )

    if not ensure_ui_exists(db, ui_id):
        raise HTTPException(status_code=404, detail="ui_id not found")

    # 1️⃣ обновляем состояние
    updated_at = upsert_ui_state(db, ui_id, mode, payload.schedule_id)
    db.commit()

    # 2️⃣ пересчитываем HW-флаги
    manual_hw, alarm, manual_topic = compute_hw_flags(db, ui_id)

    # 3️⃣ вычисляем effective mode
    mode_effective = "MANUAL_HW" if manual_hw else mode

    # 4️⃣ SSE событие UI state
    hub.publish_ui_state_threadsafe(
        UiStateChange(
            ui_id=ui_id,
            mode_effective=mode_effective,
            mode_requested=mode,
            manual_hw=manual_hw,
            manual_topic=manual_topic,
            schedule_id=payload.schedule_id,
            updated_at=updated_at.astimezone(timezone.utc).isoformat(),
        )
    )

    # 5️⃣ HTTP ответ
    return UiModeSetOut(
        ui_id=ui_id,
        mode_requested=mode,
        schedule_id=payload.schedule_id,
        updated_at=updated_at,
        manual_hw=manual_hw,
        alarm=alarm,
        mode_effective=mode_effective,
    )
