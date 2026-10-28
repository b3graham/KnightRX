"""PR screen: current bests per movement with tested / estimated / historical kept
visibly separate, plus forms to log a tested max or a pre-rhabdo historical reference."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from . import db, prs, rules, web

router = APIRouter()


def _bests():
    """Latest value per (movement, kind, source)."""
    rows = db.query("""SELECT movement_id, kind, source, value, unit, date FROM prs p
                       WHERE id IN (SELECT MAX(id) FROM prs GROUP BY movement_id, kind, source)
                       ORDER BY movement_id, kind""")
    by_mv: dict[str, list] = {}
    for r in rows:
        by_mv.setdefault(r["movement_id"], []).append(dict(r))
    return by_mv


@router.get("/prs")
async def prs_page(request: Request):
    bests = _bests()
    movements = [m for m in rules.movements() if m["id"] in bests] or []
    loggable = [m for m in rules.movements() if any(k in m.get("pr_kinds", [])
                for k in ("1RM", "3RM", "5RM", "max_reps", "max_time", "test"))]
    return web.page(request, "prs.html", bests=bests, movements=movements,
                    loggable=loggable, mv=rules.movement_by_id)


@router.post("/prs/tested")
async def log_tested(request: Request, movement_id: str = Form(...), kind: str = Form(...),
                     value: float = Form(...)):
    prs.log_tested_max(movement_id, kind, value)
    return RedirectResponse("/prs?msg=Tested+max+logged", status_code=303)


@router.post("/prs/historical")
async def log_historical(request: Request, movement_id: str = Form(...), kind: str = Form(...),
                         value: float = Form(...)):
    prs.log_historical(movement_id, kind, value)
    return RedirectResponse("/prs?msg=Historical+reference+saved+(never+used+for+programming)",
                            status_code=303)
