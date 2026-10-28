"""Movement library screen: every movement, what it needs, how it scales, whether you can
do it with your owned equipment (and what it substitutes to if not)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import rules, state, web
from .engine import scaling

router = APIRouter()


@router.get("/library")
async def library(request: Request):
    owned = state.owned_ids()
    rows = []
    for m in rules.movements():
        resolved = scaling.substitute_for_equipment(m["id"], owned)
        rows.append({
            **m,
            "available": resolved == m["id"],
            "substitute": resolved if resolved != m["id"] else None,
            "substitute_name": (rules.movement_by_id(resolved) or {}).get("name") if resolved and resolved != m["id"] else None,
        })
    cats: dict[str, list] = {}
    for r in rows:
        cats.setdefault(r["category"], []).append(r)
    return web.page(request, "library.html", cats=cats)
