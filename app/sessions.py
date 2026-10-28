"""Today flow + logging + calendar routes.

Flow: open Today -> pre-workout check-in -> red-flag screen. A red flag blocks all
programming until cleared. Otherwise the engine generates the session, which is persisted
and shown with inline logging. Completing it records the post-workout check-in and, when
the week's planned sessions are done, runs the week decision.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from . import db, rules, state, web
from .engine import generate

router = APIRouter()


def _truthy(v) -> bool:
    return str(v).lower() in ("1", "true", "on", "yes") if v is not None else False


def _checkin_from_form(**f) -> dict:
    return {
        "sleep_hours": float(f["sleep_hours"]) if f.get("sleep_hours") else None,
        "soreness": int(f["soreness"]) if f.get("soreness") not in (None, "") else None,
        "hydration": f.get("hydration"),
        "illness": _truthy(f.get("illness")),
        "redflag_dark_urine": _truthy(f.get("redflag_dark_urine")),
        "redflag_pain_swelling": _truthy(f.get("redflag_pain_swelling")),
        "redflag_weakness": _truthy(f.get("redflag_weakness")),
    }


def _today_blocked():
    on = date.today().isoformat()
    return db.query_one(
        """SELECT * FROM checkins WHERE when_phase='pre' AND blocked=1 AND cleared_confirmed=0
           AND date(created)=? ORDER BY id DESC LIMIT 1""", (on,))


@router.get("/")
async def today(request: Request):
    st = state.get_state()
    phase_def = rules.phase_def(st["phase"])
    sess = state.today_session()

    if sess is not None:
        plan = json.loads(sess["plan_json"] or "{}")
        sets = db.query("SELECT * FROM sets WHERE session_id=? ORDER BY id", (sess["id"],))
        wod_scores = db.query("SELECT * FROM wod_scores WHERE session_id=? ORDER BY id", (sess["id"],))
        return web.page(request, "today.html", view="session", st=st, phase_def=phase_def,
                        sess=sess, plan=plan, sets=sets, wod_scores=wod_scores,
                        mv=rules.movement_by_id)

    blocked = _today_blocked()
    if blocked is not None:
        return web.page(request, "today.html", view="blocked", st=st, phase_def=phase_def,
                        message=blocked["id"] and _block_message())

    return web.page(request, "today.html", view="checkin", st=st, phase_def=phase_def)


def _block_message() -> str:
    from .engine.screen import MESSAGE
    return MESSAGE.format(signs="a reported warning sign")


@router.post("/today/checkin")
async def submit_checkin(
    request: Request,
    sleep_hours: str = Form(None), soreness: str = Form(None), hydration: str = Form(None),
    illness: str = Form(None), redflag_dark_urine: str = Form(None),
    redflag_pain_swelling: str = Form(None), redflag_weakness: str = Form(None),
):
    data = _checkin_from_form(
        sleep_hours=sleep_hours, soreness=soreness, hydration=hydration, illness=illness,
        redflag_dark_urine=redflag_dark_urine, redflag_pain_swelling=redflag_pain_swelling,
        redflag_weakness=redflag_weakness)

    st = state.get_state()
    ctx = state.build_ctx(st, data)
    plan = generate.generate_session(st, ctx)

    if plan.get("blocked"):
        state.record_checkin(None, "pre", data, blocked=True)
        return RedirectResponse("/?err=Programming+blocked+by+a+warning+sign", status_code=303)

    sid = state.create_session(st, plan)
    state.record_checkin(sid, "pre", data, blocked=False)
    return RedirectResponse("/?msg=Session+ready", status_code=303)


@router.post("/today/cleared")
async def cleared(request: Request):
    on = date.today().isoformat()
    db.execute("""UPDATE checkins SET cleared_confirmed=1
                  WHERE when_phase='pre' AND blocked=1 AND date(created)=?""", (on,))
    return RedirectResponse("/?msg=Cleared+confirmed.+Re-run+your+check-in.", status_code=303)


@router.post("/today/log-set")
async def log_set(
    request: Request, session_id: int = Form(...), movement_id: str = Form(...),
    weight: str = Form(None), reps: str = Form(None), rpe: str = Form(None),
    is_wod: str = Form(None), rx: str = Form("rx"),
):
    w = float(weight) if weight else None
    r = int(reps) if reps else None
    rp = float(rpe) if rpe else None
    _, hits = state.log_set(session_id, movement_id, w, r, rp, _truthy(is_wod), rx)
    if hits:
        parts = [f"{h['kind']} {h['value']:g}{'' if h['unit']=='reps' else ' '+h['unit']} ({h['source']})"
                 for h in hits]
        return RedirectResponse(f"/?msg=New+PR!+{'+'.join(' '.join(p.split()) for p in parts)}",
                                status_code=303)
    return RedirectResponse("/?msg=Set+logged", status_code=303)


@router.post("/today/log-wod")
async def log_wod(
    request: Request, session_id: int = Form(...), format: str = Form(...),
    score_type: str = Form(...), score_value: str = Form(...), rx: str = Form("rx"),
    notes: str = Form(None),
):
    state.log_wod_score(session_id, format, score_type, score_value, rx, notes)
    return RedirectResponse("/?msg=WOD+score+logged", status_code=303)


@router.post("/today/complete")
async def complete(
    request: Request, session_id: int = Form(...), session_rpe: str = Form(None),
    redflag_dark_urine: str = Form(None), redflag_pain_swelling: str = Form(None),
    redflag_weakness: str = Form(None),
):
    post = _checkin_from_form(redflag_dark_urine=redflag_dark_urine,
                              redflag_pain_swelling=redflag_pain_swelling,
                              redflag_weakness=redflag_weakness)
    from .engine.screen import screen_redflags
    scr = screen_redflags(post)
    rpe = float(session_rpe) if session_rpe else None

    if scr["blocked"]:
        state.record_checkin(session_id, "post", post, blocked=True)
        state.complete_session(session_id, rpe)
        return RedirectResponse("/calendar?err=Warning+sign+after+training+-+seek+care+promptly",
                                status_code=303)

    state.record_checkin(session_id, "post", post, blocked=False)
    result = state.complete_session(session_id, rpe)
    if result.get("advanced"):
        msg = f"Session+done.+Next+week:+{result['decision']}"
    else:
        msg = "Session+complete.+Nice+work."
    return RedirectResponse(f"/calendar?msg={msg}", status_code=303)


@router.get("/calendar")
async def calendar(request: Request):
    st = state.get_state()
    rows = db.query("SELECT * FROM sessions ORDER BY date DESC LIMIT 21")
    decisions = db.query("SELECT * FROM week_decisions ORDER BY id DESC LIMIT 6")
    scheduled = state.training_days(st["phase"])
    summary = state.weekly_summary()
    return web.page(request, "calendar.html", st=st, sessions=rows, decisions=decisions,
                    scheduled=scheduled, phase_def=rules.phase_def(st["phase"]),
                    summary=summary, mv=rules.movement_by_id)
