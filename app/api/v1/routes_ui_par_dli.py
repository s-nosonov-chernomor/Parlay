# app/api/v1/routes_ui_par_dli.py

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas_par_dli import (
    UiParDliConfigIn,
    UiParDliConfigUpdateIn,
    UiParDliConfigOut,
)
from app.db import par_dli_crud


router = APIRouter(prefix="/par-dli", tags=["par-dli"])


@router.get("", response_model=list[UiParDliConfigOut])
def list_par_dli_configs(db: Session = Depends(get_db)):
    rows = par_dli_crud.list_configs(db)
    return [UiParDliConfigOut(**r) for r in rows]


@router.get("/{par_id}", response_model=UiParDliConfigOut)
def get_par_dli_config(par_id: str, db: Session = Depends(get_db)):
    row = par_dli_crud.get_config(db, par_id)
    if not row:
        raise HTTPException(status_code=404, detail="PAR_DLI config not found")
    return UiParDliConfigOut(**row)


@router.post("", response_model=UiParDliConfigOut)
def create_par_dli_config(payload: UiParDliConfigIn, db: Session = Depends(get_db)):
    if par_dli_crud.get_config(db, payload.par_id):
        raise HTTPException(status_code=409, detail="par_id already exists")

    row = par_dli_crud.create_config(db, payload)
    db.commit()
    return UiParDliConfigOut(**row)


@router.put("/{par_id}", response_model=UiParDliConfigOut)
def update_par_dli_config(par_id: str, payload: UiParDliConfigUpdateIn, db: Session = Depends(get_db)):
    row = par_dli_crud.update_config(db, par_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="PAR_DLI config not found")
    db.commit()
    return UiParDliConfigOut(**row)


@router.delete("/{par_id}")
def delete_par_dli_config(par_id: str, db: Session = Depends(get_db)):
    deleted = par_dli_crud.delete_config(db, par_id)
    db.commit()
    return {"ok": bool(deleted), "deleted": deleted}