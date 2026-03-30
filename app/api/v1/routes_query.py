# app/api/v1/routes_query.py
from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session


from app.api.deps import get_db, require_authenticated
from app.api.auth import require_token
from app.services.query_service import QueryService
from app.services.excel_export import build_xlsx
from app.api.v1.schemas_query import (
    QueryRunIn,
    QueryRunOut,
    QueryRowOut,
    QueryDliIn,
    QueryDliOut,
    QueryDliRowOut,
)

router = APIRouter(prefix="/query", tags=["query"])

svc = QueryService()


@router.post("/run", response_model=QueryRunOut)
def query_run(payload: QueryRunIn, current_user=Depends(require_authenticated), db: Session = Depends(get_db)):
    rows, meta = svc.run(
        db=db,
        ui_ids=payload.ui_ids,
        bind_keys=payload.bind_keys,
        start=payload.start,
        end=payload.end,
        bucket_s=payload.bucket_s,
        limit=payload.limit,
    )
    columns = ["ts", "ui_id", "zone_code", "source_id", "bind_key", "note", "topic", "value_num", "value_text"]
    return {
        "rows": [QueryRowOut(**r) for r in rows],
        "columns": columns,
        "meta": meta,
    }


@router.post("/export.xlsx", dependencies=[Depends(require_token)])
def query_export_xlsx(payload: QueryRunIn, current_user=Depends(require_authenticated), db: Session = Depends(get_db)):
    rows, meta = svc.run(
        db=db,
        ui_ids=payload.ui_ids,
        bind_keys=payload.bind_keys,
        start=payload.start,
        end=payload.end,
        bucket_s=payload.bucket_s,
        limit=payload.limit,
    )
    content = build_xlsx(rows, meta)

    fname = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{fname}"'
    }
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )

@router.post("/dli", response_model=QueryDliOut)
def query_dli(payload: QueryDliIn, current_user=Depends(require_authenticated), db: Session = Depends(get_db)):
    rows, meta = svc.calc_dli(
        db=db,
        ui_ids=payload.ui_ids,
        par_sum_bind_key=payload.par_sum_bind_key,
        enabled_bind_keys=payload.enabled_bind_keys,
        start=payload.start,
        end=payload.end,
        dli_cap_umol=payload.dli_cap_umol,
    )

    return {
        "rows": [QueryDliRowOut(**r) for r in rows],
        "meta": meta,
    }