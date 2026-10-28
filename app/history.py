"""History screen: a progress chart per movement (hand-rolled SVG fed by /api/history) and
the list of movements with logged history."""
from __future__ import annotations

from fastapi import APIRouter, Request

from . import db, rules, state, web

router = APIRouter()


@router.get("/history")
async def history(request: Request):
    rows = db.query("""SELECT movement_id, COUNT(*) n, MAX(date) last FROM prs
                       WHERE source != 'historical' GROUP BY movement_id ORDER BY last DESC""")
    movements = [{"id": r["movement_id"], "name": (rules.movement_by_id(r["movement_id"]) or {}).get("name", r["movement_id"]),
                  "n": r["n"], "last": r["last"]} for r in rows]
    return web.page(request, "history.html", movements=movements)


@router.get("/api/history")
async def api_history(movement: str):
    return state.history_series(movement)
