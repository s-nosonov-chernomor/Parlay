# app/api/v1/routes_parameters.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.schemas import ParameterOut
from app.db.models import Parameter

router = APIRouter(prefix="/parameters", tags=["parameters"])


@router.get("", response_model=list[ParameterOut])
def list_parameters(
    prefix: str | None = Query(default=None, description="Фильтр по началу topic, например '/Черноморье/Дом/'"),
    limit: int = 5000,
    db: Session = Depends(get_db),
):
    stmt = select(Parameter)
    if prefix:
        stmt = stmt.where(Parameter.topic.like(prefix + "%"))
    stmt = stmt.order_by(Parameter.topic.asc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        ParameterOut(
            id=p.id,
            topic=p.topic,
            title=p.title,
            kind=p.kind,
            unit=p.unit,
            is_control=p.is_control,
        )
        for p in rows
    ]


@router.get("/tree")
def parameters_tree(
    prefix: str | None = Query(default=None, description="Корень дерева (prefix)"),
    limit: int = 20000,
    db: Session = Depends(get_db),
):
    """
    Возвращает дерево по разделителю '/'.
    Фронту удобно рисовать навигацию.
    """
    stmt = select(Parameter.topic).order_by(Parameter.topic.asc()).limit(limit)
    if prefix:
        stmt = stmt.where(Parameter.topic.like(prefix + "%"))

    topics = [t for (t,) in db.execute(stmt).all()]

    root: dict = {"name": prefix or "/", "children": {}}

    for topic in topics:
        parts = [p for p in topic.split("/") if p]  # убираем пустые из-за ведущего '/'
        node = root["children"]
        for part in parts:
            node = node.setdefault(part, {"children": {}})["children"]

    def freeze(name: str, node: dict) -> dict:
        children = node.get("children", {})
        return {
            "name": name,
            "children": [freeze(k, v) for k, v in children.items()],
        }

    return freeze(root["name"], {"children": root["children"]})
