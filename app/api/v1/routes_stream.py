# app/api/v1/routes_stream.py
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Query, Request, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.sse.hub import hub

router = APIRouter(prefix="/readings", tags=["readings"])


@router.get("/stream")
async def stream_readings(
    request: Request,
    topics: list[str] | None = Query(default=None),
    prefix: str | None = Query(default=None),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    """
    SSE stream по списку topics или по prefix.
    """
    # normalise filters
    topic_set = set(topics) if topics else None

    if not topic_set and not prefix:
        raise HTTPException(status_code=400, detail="Provide either topics or prefix")

    # поддержка Last-Event-ID (best-effort)
    lei_int: Optional[int] = None
    if last_event_id:
        try:
            lei_int = int(last_event_id.strip())
        except Exception:
            lei_int = None

    loop = asyncio.get_running_loop()
    client = hub.connect(
        loop=loop,
        topics=topic_set,
        prefix=prefix,
        last_event_id=lei_int,
        flush_interval_ms=150,
        heartbeat_s=15,
    )

    async def gen():
        try:
            # полезно отправить "hello" сразу, чтобы прокси не ждали
            yield "event: hello\nid: 0\ndata: {}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    chunk = await asyncio.wait_for(client.drain(), timeout=5.0)
                    yield chunk
                except asyncio.TimeoutError:
                    # просто даём шанс проверить disconnect и не зависнуть
                    continue

        finally:
            hub.disconnect(client)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # важно для nginx
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
