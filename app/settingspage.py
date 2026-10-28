"""Settings: equipment ownership + KB/med-ball weights, training days per phase, and a
phase override (with a confirmation warning, since overriding skips the readiness gates)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from . import db, rules, state, web

router = APIRouter()
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@router.get("/settings")
async def settings_page(request: Request):
    equipment = db.query("SELECT * FROM equipment ORDER BY category, name")
    st = state.get_state()
    sett = db.query_one("SELECT * FROM app_settings WHERE id=1")
    training = json.loads(sett["training_days"]) if sett else {}
    return web.page(request, "settings.html", equipment=equipment, st=st, days=DAYS,
                    training=training, phases=rules.phases(),
                    weekdays={str(p["phase"]): state.training_days(p["phase"]) for p in rules.phases()})


@router.post("/settings/equipment")
async def save_equipment(request: Request):
    form = await request.form()
    for e in db.query("SELECT id, multi_weight FROM equipment"):
        owned = 1 if form.get(f"owned_{e['id']}") else 0
        args = [owned]
        sql = "UPDATE equipment SET owned=?"
        if e["multi_weight"]:
            raw = (form.get(f"weights_{e['id']}") or "").strip()
            weights = sorted({int(float(x)) for x in raw.replace(",", " ").split() if x.strip()}) if raw else []
            sql += ", weights=?"
            args.append(json.dumps(weights))
        sql += " WHERE id=?"
        args.append(e["id"])
        db.execute(sql, tuple(args))
    return RedirectResponse("/settings?msg=Equipment+saved", status_code=303)


@router.post("/settings/training-days")
async def save_training_days(request: Request):
    form = await request.form()
    mapping: dict[str, list] = {}
    for p in rules.phases():
        chosen = [d for d in DAYS if form.get(f"day_{p['phase']}_{d}")]
        if chosen:
            mapping[str(p["phase"])] = chosen[: p["days_per_week_max"]]
    if not mapping:
        mapping = {"default": ["Mon", "Wed", "Fri"]}
    db.execute("UPDATE app_settings SET training_days=? WHERE id=1", (json.dumps(mapping),))
    return RedirectResponse("/settings?msg=Training+days+saved", status_code=303)


@router.post("/settings/phase-override")
async def phase_override(request: Request, phase: int = Form(...), confirm: str = Form(None)):
    if not confirm:
        return RedirectResponse("/settings?err=Phase+override+needs+confirmation", status_code=303)
    st = state.get_state()
    st["phase"] = phase
    st["week_in_phase"] = 1
    st["program_week"] = rules.phase_def(phase)["week_start"]
    state.save_state(st)
    db.execute("UPDATE app_settings SET phase_override=? WHERE id=1", (phase,))
    return RedirectResponse(f"/settings?msg=Phase+set+to+{phase}+(override)", status_code=303)
