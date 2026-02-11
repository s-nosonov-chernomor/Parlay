# app/api/v1/routes_ui_stream.py
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db import ui_snapshot_crud as crud
from app.sse.hub import hub


router = APIRouter(prefix="/ui/page", tags=["ui"])


@router.get("/{page}/stream")
async def ui_page_stream(
    page: str,
    request: Request,
    db: Session = Depends(get_db),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    elements = crud.load_elements(db, page)
    if not elements:
        raise HTTPException(status_code=404, detail="page not found or empty")

    ui_ids = [e.ui_id for e in elements]
    bindings = crud.load_bindings(db, ui_ids)

    topics = {b.topic for b in bindings if b.topic}

    # ✅ добавляем виртуальные UI-state топики, чтобы страница точно получала смену mode/manual_hw
    for ui_id in ui_ids:
        topics.add(f"ui:{ui_id}:state")

    if not topics:
        raise HTTPException(status_code=404, detail="page has no topics")

    lei_int: Optional[int] = None
    if last_event_id:
        try:
            lei_int = int(last_event_id.strip())
        except Exception:
            lei_int = None

    loop = asyncio.get_running_loop()
    client = hub.connect(
        loop=loop,
        topics=set(topics),
        prefix=None,
        last_event_id=lei_int,
        flush_interval_ms=150,
        heartbeat_s=15,
    )

    async def gen():
        try:
            yield "event: hello\nid: 0\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    chunk = await asyncio.wait_for(client.drain(), timeout=5.0)
                    yield chunk
                except asyncio.TimeoutError:
                    continue
        finally:
            hub.disconnect(client)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
