"""Glue between the database and the pure engine.

Builds the engine's context from stored data (owned equipment, weekly conditioning volume
by ISO calendar week, movement introductions, programming maxes), persists generated
sessions, logs sets with automatic PR detection, and runs the week decision on completion.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

from . import db, prs, rules
from .engine import caps as caps_mod
from .engine import generate, progression


# --- program state -------------------------------------------------------------
def get_state() -> dict:
    row = db.query_one("SELECT * FROM program_state WHERE id=1")
    d = dict(row)
    d["is_deload"] = bool(d.get("last_decision") == "deload")
    return d


def save_state(state: dict) -> None:
    db.execute(
        """UPDATE program_state SET phase=?, program_week=?, week_in_phase=?,
           last_decision=?, last_decision_reason=?, last_session_date=? WHERE id=1""",
        (state["phase"], state["program_week"], state["week_in_phase"],
         state.get("last_decision"), state.get("last_decision_reason"),
         state.get("last_session_date")))


# --- settings / equipment ------------------------------------------------------
def owned_ids() -> set[str]:
    return {r["id"] for r in db.query("SELECT id FROM equipment WHERE owned=1")}


def training_days(phase: int) -> list[str]:
    row = db.query_one("SELECT training_days FROM app_settings WHERE id=1")
    days = json.loads(row["training_days"]) if row else {}
    return days.get(str(phase)) or days.get("default") or ["Mon", "Wed", "Fri"]


def maxes_fn():
    return lambda mid: prs.programming_max(mid)


# --- volume / history helpers --------------------------------------------------
def _iso_week(d: str) -> tuple[int, int]:
    y, w, _ = datetime.fromisoformat(d).isocalendar()
    return (y, w)


def _wod_volume(plan: dict) -> dict[str, int]:
    vol: dict[str, int] = defaultdict(int)
    for mv in plan.get("wod", {}).get("movements", []):
        if mv.get("cap_key"):
            vol[mv["cap_key"]] += int(mv.get("planned_total", 0))
    return vol


def _completed_plans() -> list[tuple[str, dict]]:
    rows = db.query("SELECT date, plan_json FROM sessions WHERE status='completed' ORDER BY date")
    return [(r["date"], json.loads(r["plan_json"] or "{}")) for r in rows]


def week_volumes(ref_date: str) -> tuple[dict, dict]:
    """Return (last_week_vol, this_week_done) WOD volumes relative to ref_date's ISO week."""
    this_wk = _iso_week(ref_date)
    # previous ISO week = the week of 7 days earlier
    from datetime import timedelta
    prev_wk = _iso_week((datetime.fromisoformat(ref_date) - timedelta(days=7)).date().isoformat())
    last_vol, this_vol = defaultdict(int), defaultdict(int)
    for d, plan in _completed_plans():
        wk = _iso_week(d)
        v = _wod_volume(plan)
        if wk == prev_wk:
            for k, n in v.items():
                last_vol[k] += n
        elif wk == this_wk:
            for k, n in v.items():
                this_vol[k] += n
    return dict(last_vol), dict(this_vol)


def introductions_and_established() -> tuple[dict, set]:
    intro: dict[str, int] = defaultdict(int)
    for _, plan in _completed_plans():
        for mv in plan.get("wod", {}).get("movements", []):
            intro[mv["movement_id"]] += 1
        if plan.get("strength"):
            intro[plan["strength"]["movement_id"]] += 0  # noted, not counted as a WOD intro
    req = rules.introduce_sessions_required()
    established = {mid for mid, c in intro.items() if c >= req}
    # Any movement with a PR counts as practiced/established too.
    for r in db.query("SELECT DISTINCT movement_id FROM prs WHERE source != 'historical'"):
        established.add(r["movement_id"])
    return dict(intro), established


def sessions_this_week(ref_date: str) -> int:
    this_wk = _iso_week(ref_date)
    n = 0
    for r in db.query("SELECT date FROM sessions WHERE status IN ('completed','planned')"):
        if _iso_week(r["date"]) == this_wk:
            n += 1
    return n


# --- today / sessions ----------------------------------------------------------
def today_session(on: str | None = None):
    on = on or date.today().isoformat()
    return db.query_one("SELECT * FROM sessions WHERE date=? ORDER BY id DESC LIMIT 1", (on,))


def build_ctx(state: dict, checkin: dict, on: str | None = None) -> dict:
    on = on or date.today().isoformat()
    last_vol, this_done = week_volumes(on)
    intro, established = introductions_and_established()
    return {
        "owned_ids": owned_ids(),
        "checkin": checkin,
        "last_week_vol": last_vol,
        "this_week_done": this_done,
        "introductions": intro,
        "established": established,
        "maxes": maxes_fn(),
        "day_index": sessions_this_week(on),
    }


def create_session(state: dict, plan: dict, on: str | None = None) -> int:
    on = on or date.today().isoformat()
    return db.execute(
        """INSERT INTO sessions
           (date, phase, program_week, week_in_phase, day_index, status, plan_json,
            is_deload, is_active_recovery)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (on, plan["phase"], plan["program_week"], plan.get("week_in_phase", 1),
         plan.get("day_index", 0), "planned", json.dumps(plan),
         int(plan.get("is_deload", False)), int(plan.get("is_active_recovery", False))))


def record_checkin(session_id: int | None, when_phase: str, data: dict, blocked: bool) -> int:
    return db.execute(
        """INSERT INTO checkins
           (session_id, when_phase, sleep_hours, soreness, hydration, illness,
            redflag_dark_urine, redflag_pain_swelling, redflag_weakness, blocked, created)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (session_id, when_phase, data.get("sleep_hours"), data.get("soreness"),
         data.get("hydration"), int(bool(data.get("illness"))),
         int(bool(data.get("redflag_dark_urine"))), int(bool(data.get("redflag_pain_swelling"))),
         int(bool(data.get("redflag_weakness"))), int(blocked), datetime.now().isoformat()))


def log_set(session_id: int, movement_id: str, weight, reps, rpe, is_wod: bool,
            rx: str) -> tuple[int, list[dict]]:
    set_id = db.execute(
        """INSERT INTO sets (session_id, movement_id, set_index, weight, reps, rpe,
           is_wod, rx_or_scaled, created) VALUES (?,?,?,?,?,?,?,?,?)""",
        (session_id, movement_id,
         db.query_one("SELECT COUNT(*) c FROM sets WHERE session_id=? AND movement_id=?",
                      (session_id, movement_id))["c"],
         weight, reps, rpe, int(is_wod), rx, datetime.now().isoformat()))
    movement = rules.movement_by_id(movement_id) or {}
    hits = prs.detect_from_set(movement, weight, reps)
    if hits:
        prs.record_prs(movement_id, hits, source_set_id=set_id)
    return set_id, hits


def log_wod_score(session_id: int, fmt: str, score_type: str, score_value: str,
                  rx: str, notes: str | None = None) -> int:
    return db.execute(
        """INSERT INTO wod_scores (session_id, format, score_type, score_value, rx_or_scaled, notes)
           VALUES (?,?,?,?,?,?)""",
        (session_id, fmt, score_type, score_value, rx, notes))


def complete_session(session_id: int, session_rpe: float | None) -> dict:
    row = db.query_one("SELECT * FROM sessions WHERE id=?", (session_id,))
    db.execute("UPDATE sessions SET status='completed', session_rpe=? WHERE id=?",
               (session_rpe, session_id))
    state = get_state()
    state["last_session_date"] = row["date"]
    save_state(state)
    return _maybe_decide_week(state, row["date"])


def _maybe_decide_week(state: dict, on: str) -> dict:
    """If the planned sessions for this ISO week are done, decide and advance to next week."""
    phase_def = rules.phase_def(state["phase"])
    planned = phase_def["days_per_week"]
    completed_this_week = sessions_completed_this_week(on)
    if completed_this_week < planned:
        return {"advanced": False}

    rpes = [r["session_rpe"] for r in db.query(
        "SELECT session_rpe FROM sessions WHERE status='completed' AND session_rpe IS NOT NULL")][-planned:]
    sores = _recent_week_soreness(on)
    prev = {"completed": completed_this_week, "planned": planned,
            "avg_soreness": (sum(sores) / len(sores)) if sores else None,
            "avg_rpe": (sum(rpes) / len(rpes)) if rpes else None,
            "had_gap": _had_gap(state, on)}
    decision, reason = progression.decide_week(state["program_week"] + 1, prev, phase_def["rpe_cap"])
    db.execute("INSERT INTO week_decisions (program_week, phase, decision, reason, created) VALUES (?,?,?,?,?)",
               (state["program_week"], state["phase"], decision, reason, datetime.now().isoformat()))
    new = progression.apply_decision(state, decision)
    new["last_decision"] = decision
    new["last_decision_reason"] = reason
    new["last_session_date"] = on
    save_state(new)
    return {"advanced": True, "decision": decision, "reason": reason}


def sessions_completed_this_week(ref_date: str) -> int:
    this_wk = _iso_week(ref_date)
    return sum(1 for r in db.query("SELECT date FROM sessions WHERE status='completed'")
               if _iso_week(r["date"]) == this_wk)


def _recent_week_soreness(ref_date: str) -> list[int]:
    this_wk = _iso_week(ref_date)
    out = []
    for r in db.query("""SELECT c.soreness, s.date FROM checkins c JOIN sessions s ON c.session_id=s.id
                         WHERE c.when_phase='pre' AND c.soreness IS NOT NULL"""):
        if _iso_week(r["date"]) == this_wk:
            out.append(r["soreness"])
    return out


def weekly_summary(ref_date: str | None = None) -> dict:
    """This week's sessions, conditioning volume vs the per-session caps, PRs hit, the last
    week decision, and a 'never miss twice' nudge."""
    on = ref_date or date.today().isoformat()
    st = get_state()
    phase_def = rules.phase_def(st["phase"])
    this_wk = _iso_week(on)

    vol: dict[str, int] = defaultdict(int)
    for d, plan in _completed_plans():
        if _iso_week(d) == this_wk:
            for k, n in _wod_volume(plan).items():
                vol[k] += n
    volume = [{"cap_key": k, "done": v,
               "cap": caps_mod.session_cap_for(k, st["phase"], False)} for k, v in sorted(vol.items())]

    prs_week = []
    for r in db.query("SELECT * FROM prs WHERE source != 'historical' ORDER BY id DESC"):
        if _iso_week(r["date"]) == this_wk:
            prs_week.append(dict(r))

    # never-miss-twice nudge
    last = st.get("last_session_date")
    gap_days = (datetime.fromisoformat(on) - datetime.fromisoformat(last)).days if last else None
    if gap_days is not None and gap_days >= 2:
        nudge = f"It's been {gap_days} days. Do something today — even active recovery. Never miss twice."
        nudge_level = "warn"
    elif gap_days == 1:
        nudge = "Yesterday was a rest day — today's session matters. Don't miss twice."
        nudge_level = "ok"
    else:
        nudge = "On track. Consistency beats intensity."
        nudge_level = "ok"

    return {
        "completed": sessions_completed_this_week(on), "planned": phase_def["days_per_week"],
        "volume": volume, "prs": prs_week,
        "decision": st.get("last_decision"), "reason": st.get("last_decision_reason"),
        "nudge": nudge, "nudge_level": nudge_level,
    }


def history_series(movement_id: str) -> dict:
    """Non-historical PR points over time for one movement, for the progress chart."""
    rows = db.query("""SELECT date, value, kind, source FROM prs
                       WHERE movement_id=? AND source != 'historical' ORDER BY date""", (movement_id,))
    m = rules.movement_by_id(movement_id) or {}
    return {"movement": movement_id, "name": m.get("name", movement_id),
            "series": [dict(r) for r in rows]}


def _had_gap(state: dict, on: str) -> bool:
    """True if there was a >=7-day gap between the two most recent completed sessions."""
    rows = db.query("SELECT date FROM sessions WHERE status='completed' ORDER BY date DESC LIMIT 2")
    if len(rows) < 2:
        return False
    delta = (datetime.fromisoformat(rows[0]["date"]) - datetime.fromisoformat(rows[1]["date"])).days
    return delta >= rules.phase_globals()["gap_reset_days"]
