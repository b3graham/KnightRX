"""The safety proof (spec requirement #3).

Simulate 14 weeks of programming across a matrix of check-in inputs and assert that the
engine NEVER violates a rhabdo guardrail:
  - per-session volume cap (strength + WOD) for any movement bucket,
  - the <=10% week-over-week conditioning ramp,
  - the phase / min_phase lock on every movement,
  - skill prerequisites (e.g. kipping requires strict-pull established),
  - the "introduce an eccentric/high-risk movement at low volume twice first" rule,
  - equipment: nothing is ever programmed that the athlete can't do with what they own.
A separate test proves any red flag blocks all programming.
"""
import math
from collections import defaultdict

from app import rules
from app.engine import caps, generate, progression, screen

OWNED = {e["id"] for e in rules.equipment() if e.get("owned")}
RAMP = 1.0 + rules.weekly_ramp_pct()
REQ = rules.introduce_sessions_required()


def _maxes():
    base = {"back_squat": 185, "front_squat": 135, "deadlift": 205, "press": 95,
            "push_press": 115, "bench_press": 135, "power_clean": 115, "thruster": 95}
    return lambda mid: base.get(mid)


def _checkin(week: int, day: int) -> dict:
    sore = [2, 4, 6, 8, 3, 7][(week + day) % 6]
    sleep = [8, 7, 6, 5, 7, 6][(week * 2 + day) % 6]
    illness = ((week * 7 + day) % 23) == 0
    return {"soreness": sore, "sleep_hours": sleep, "illness": illness,
            "redflag_dark_urine": False, "redflag_pain_swelling": False,
            "redflag_weakness": False}


def _simulate(weeks: int = 14):
    """Run the engine week by week; return every (state, intro_snapshot, established_snapshot,
    plan) tuple plus the per-week WOD volumes for the ramp check."""
    state = {"phase": 0, "program_week": 1, "week_in_phase": 1, "is_deload": False}
    introductions: dict[str, int] = defaultdict(int)
    established: set[str] = set()
    last_week_vol: dict[str, int] = {}
    maxes = _maxes()
    records = []
    week_volumes = []  # (prev_week_vol, this_week_vol) pairs for the ramp assertion

    for w in range(1, weeks + 1):
        phase_def = rules.phase_def(state["phase"])
        days = phase_def["days_per_week"]
        this_week_vol: dict[str, int] = defaultdict(int)
        week_sore, completed = [], 0

        for d in range(days):
            ci = _checkin(w, d)
            intro_snap = dict(introductions)
            est_snap = set(established)
            ctx = {"owned_ids": OWNED, "checkin": ci, "last_week_vol": dict(last_week_vol),
                   "this_week_done": dict(this_week_vol), "introductions": intro_snap,
                   "established": est_snap, "maxes": maxes, "day_index": d}
            plan = generate.generate_session(state, ctx)
            records.append((dict(state), intro_snap, est_snap, plan))

            if plan.get("blocked"):
                continue
            completed += 1
            if plan.get("is_active_recovery"):
                continue
            for k, v in caps.wod_usage(plan).items():
                this_week_vol[k] += v
            for mv in plan["wod"]["movements"]:
                introductions[mv["movement_id"]] += 1
                if introductions[mv["movement_id"]] >= REQ:
                    established.add(mv["movement_id"])
            if plan.get("strength"):
                established.add(plan["strength"]["movement_id"])
            week_sore.append(max(ci["soreness"] - 1, 0))

        week_volumes.append((dict(last_week_vol), dict(this_week_vol)))
        prev = {"completed": completed, "planned": days,
                "avg_soreness": (sum(week_sore) / len(week_sore)) if week_sore else None,
                "avg_rpe": phase_def["rpe_cap"], "had_gap": (w == 9)}
        decision, _ = progression.decide_week(state["program_week"] + 1, prev, phase_def["rpe_cap"])
        last_week_vol = dict(this_week_vol)
        state = progression.apply_decision(state, decision)

    return records, week_volumes


def test_no_guardrail_is_ever_violated():
    records, week_volumes = _simulate(14)
    assert len(records) >= 36  # 14 weeks of 3-4 days

    for state, intro_snap, est_snap, plan in records:
        if plan.get("blocked") or plan.get("is_active_recovery"):
            continue
        phase, is_deload = state["phase"], state["is_deload"]

        # 1. per-session cap (strength + WOD) never exceeded
        for k, v in caps.session_cap_usage(plan).items():
            cap = caps.session_cap_for(k, phase, is_deload)
            if cap is not None:
                assert v <= cap, f"session cap {k}: {v} > {cap} at phase {phase}"

        strength_ids = [plan["strength"]["movement_id"]] if plan.get("strength") else []
        wod = plan["wod"]["movements"]

        # 2. phase / min_phase lock
        for mid in strength_ids + [m["movement_id"] for m in wod]:
            m = rules.movement_by_id(mid)
            assert m["min_phase"] <= phase, f"{mid} min_phase {m['min_phase']} > {phase}"

        # 3. equipment ownership (everything is performable with what's owned)
        for mid in strength_ids + [m["movement_id"] for m in wod]:
            req_eq = rules.movement_by_id(mid).get("equipment", [])
            assert set(req_eq) <= OWNED, f"{mid} needs unowned equipment {req_eq}"

        # 4. skill prerequisites established at generation time
        for m in wod:
            for p in rules.movement_by_id(m["movement_id"]).get("skill_prereqs", []):
                assert p in est_snap, f"{m['movement_id']} programmed before {p} established"

        # 5. introduce-twice: novel eccentric/high-risk movement stays at low volume
        for m in wod:
            md = rules.movement_by_id(m["movement_id"])
            if (md.get("eccentric_heavy") or md.get("high_risk")) and intro_snap.get(m["movement_id"], 0) < REQ:
                cap = caps.session_cap_for(md.get("cap_key"), phase, is_deload)
                intro_cap = max(m["reps_per_set"], int((cap or m["planned_total"]) * generate.INTRO_FRACTION))
                assert m["planned_total"] <= intro_cap, (
                    f"{m['movement_id']} high volume {m['planned_total']} before introduced "
                    f"({intro_snap.get(m['movement_id'], 0)}/{REQ})")

    # 6. weekly conditioning ramp <= 10% WoW
    for prev_vol, this_vol in week_volumes:
        for k, v in this_vol.items():
            prev = prev_vol.get(k, 0)
            if prev > 0:
                assert v <= math.floor(prev * RAMP), f"{k} ramp: {v} > {math.floor(prev * RAMP)}"


def test_program_actually_progresses_through_phases():
    records, _ = _simulate(20)
    phases_seen = {state["phase"] for state, *_ in records}
    assert 0 in phases_seen and 1 in phases_seen  # re-entry into foundation at least
    assert max(phases_seen) >= 2                   # reaches Build within 20 weeks


def test_red_flag_blocks_all_programming():
    for flag in ("redflag_dark_urine", "redflag_pain_swelling", "redflag_weakness"):
        ci = {"soreness": 2, "sleep_hours": 8, "illness": False,
              "redflag_dark_urine": False, "redflag_pain_swelling": False, "redflag_weakness": False}
        ci[flag] = True
        state = {"phase": 2, "program_week": 12, "week_in_phase": 2, "is_deload": False}
        plan = generate.generate_session(state, {"owned_ids": OWNED, "checkin": ci, "maxes": _maxes()})
        assert plan["blocked"] is True
        assert plan["wod"]["movements"] == []
        assert "seek medical care" in plan["stimulus"].lower()


def test_screen_is_clean_when_no_flags():
    assert screen.screen_redflags({"soreness": 9, "illness": True})["blocked"] is False
