"""Deterministic session assembly. Given program state + a pre-workout check-in, build one
session: warm-up, strength, WOD, cool-down. No randomness, no LLM — same inputs, same plan.

Order of operations (each a hard gate for the next):
  red-flag screen -> readiness scale -> (active recovery?) -> strength -> WOD
  -> equipment substitution -> introduce-twice gate -> safety caps.
The safety caps run last, so nothing can raise volume above the ceiling.
"""
from __future__ import annotations

from .. import rules
from . import caps, scaling, screen

WOD_CATEGORIES = {"gymnastics", "kettlebell", "ball", "monostructural"}
WOD_BARBELL_OK = {"thruster", "power_clean", "push_press"}
STRENGTH_LIFTS = ["back_squat", "press", "deadlift", "front_squat", "push_press",
                  "bench_press", "power_clean"]

# Reps per working set in a WOD, by movement cap_key (fallbacks below).
REPS_PER_SET = {
    "pullups": 5, "pushups": 10, "air_squats": 15, "kb_swings": 12, "wallballs": 10,
    "lunges": 10, "burpees": 8, "thrusters": 8, "squats_loaded": 10,
}
MONO_PER_SET = {"bike": 10, "row": 10, "jump_rope_singles": 30, "double_unders": 20, "run": 200}
ROUNDS_BY_PHASE = {0: 3, 1: 4, 2: 5, 3: 5}
INTRO_FRACTION = 0.3   # novel eccentric movements get <=30% of cap until introduced twice


# --- helpers -------------------------------------------------------------------
def _resolvable(movement_id: str, owned: set[str]) -> str | None:
    return scaling.substitute_for_equipment(movement_id, owned)


def _established(mid: str, established: set[str]) -> bool:
    return mid in established


def _reps_per_set(m: dict) -> int:
    if m["id"] in MONO_PER_SET:
        return MONO_PER_SET[m["id"]]
    if m.get("cap_key") in REPS_PER_SET:
        return REPS_PER_SET[m["cap_key"]]
    return 10


# --- strength ------------------------------------------------------------------
def prescribe_strength(phase: int, phase_def: dict, program_week: int, day_index: int,
                       maxes, owned: set[str], factor: float, is_deload: bool) -> dict | None:
    lifts = [lid for lid in STRENGTH_LIFTS
             if (rules.movement_by_id(lid) or {}).get("min_phase", 0) <= phase
             and _resolvable(lid, owned) == lid]
    if not lifts:
        return None
    lid = lifts[(program_week + day_index) % len(lifts)]
    m = rules.movement_by_id(lid)
    spec = phase_def["strength"]
    sets, reps = spec["sets"], spec["reps"]
    if is_deload:
        sets = max(1, round(sets * rules.deload_volume_multiplier()))

    load: dict = {}
    mode = spec.get("load_mode", "rpe")
    est = maxes(lid) if callable(maxes) else (maxes or {}).get(lid)
    if mode == "pct_est" and est:
        pct = spec["pct"] * (factor if factor < 1.0 else 1.0)
        weight = max(45, round(est * pct / 5.0) * 5)   # nearest 5 lb, never below an empty bar
        load = {"type": "pct", "pct": round(pct, 2), "weight": weight, "of_est_1rm": round(est, 1)}
    else:
        load = {"type": "rpe", "rpe": spec.get("rpe", phase_def["rpe_cap"]),
                "cue": "empty or light bar — own the technique"}

    return {"movement_id": lid, "name": m["name"], "sets": sets, "reps": reps,
            "load": load, "cap_key": m.get("cap_key"), "planned_total": sets * reps}


# --- WOD -----------------------------------------------------------------------
def _wod_pool(phase: int, owned: set[str], established: set[str], is_deload: bool) -> list[dict]:
    pool: list[dict] = []
    seen: set[str] = set()
    for m in rules.movements():
        if m.get("min_phase", 0) > phase:
            continue
        if m["category"] not in WOD_CATEGORIES and m["id"] not in WOD_BARBELL_OK:
            continue
        if caps.session_cap_for(m.get("cap_key"), phase, is_deload) == 0:
            continue  # bucket not allowed at this phase
        prereqs = m.get("skill_prereqs", [])
        if prereqs and not all(_established(p, established) for p in prereqs):
            continue
        resolved = _resolvable(m["id"], owned)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        pool.append(rules.movement_by_id(resolved))
    return pool


def build_wod(phase: int, phase_def: dict, program_week: int, day_index: int,
              owned: set[str], introductions: dict[str, int], established: set[str],
              factor: float, is_deload: bool, maxes) -> dict:
    fmt = phase_def["wod_formats"][day_index % len(phase_def["wod_formats"])]
    pool = _wod_pool(phase, owned, established, is_deload)
    if not pool:
        pool = [rules.movement_by_id("bike")]

    n = min(phase_def["wod_movements_max"], len(pool))
    start = (program_week * 7 + day_index) % len(pool)
    picks, i = [], 0
    while len(picks) < n and i < len(pool):
        picks.append(pool[(start + i) % len(pool)])
        i += 1

    rounds = ROUNDS_BY_PHASE.get(phase, 3)
    if is_deload:
        rounds = max(1, round(rounds * rules.deload_volume_multiplier()))
    rounds = max(1, round(rounds * factor)) if factor < 1.0 else rounds

    req = rules.introduce_sessions_required()
    movements = []
    for m in picks:
        rps = _reps_per_set(m)
        planned = rps * rounds
        note = None
        # Introduce-twice gate: a novel eccentric/high-risk movement stays at low volume
        # until it has been introduced at low volume in >= required prior sessions.
        if (m.get("eccentric_heavy") or m.get("high_risk")) and introductions.get(m["id"], 0) < req:
            cap = caps.session_cap_for(m.get("cap_key"), phase, is_deload)
            intro_cap = max(rps, int((cap or planned) * INTRO_FRACTION))
            if planned > intro_cap:
                planned = intro_cap
                note = f"introductory low volume ({introductions.get(m['id'], 0)}/{req} intros)"
        mv = {"movement_id": m["id"], "name": m["name"], "cap_key": m.get("cap_key"),
              "reps_per_set": rps, "planned_total": planned, "unit": m["unit"]}
        if note:
            mv["scaled_note"] = note
        # Light loads for loaded WOD movements.
        if m["unit"] == "lb":
            mv["load"] = _wod_load(m, maxes, owned)
        movements.append(mv)

    return {"format": fmt, "time_cap_min": phase_def["wod_min"][1], "rounds_target": rounds,
            "movements": movements,
            "stimulus": _stimulus(fmt, phase_def["rpe_cap"], is_deload)}


def _wod_load(m: dict, maxes, owned: set[str]) -> dict:
    if m["category"] == "kettlebell" or m["id"].startswith("kb_") or m["id"] == "kb_swing":
        kb = rules.equipment_by_id("kettlebell") or {}
        weights = sorted(kb.get("weights", []) or [26])
        return {"type": "absolute", "weight": weights[0], "unit": "lb", "note": "lightest bell"}
    if m["id"] == "wall_ball":
        wb = rules.equipment_by_id("wall_ball") or {}
        w = (wb.get("weights", [14]) or [14])[0]
        return {"type": "absolute", "weight": w, "unit": "lb"}
    est = maxes(m["id"]) if callable(maxes) else None
    if est:
        return {"type": "pct", "pct": 0.40, "weight": max(45, round(est * 0.4 / 5) * 5)}
    return {"type": "absolute", "weight": 45, "unit": "lb", "note": "empty bar"}


def _stimulus(fmt: str, rpe_cap: int, is_deload: bool) -> str:
    if is_deload:
        return "Deload: smooth and easy, well short of failure. This week is for recovery."
    base = {
        "steady": "Steady, conversational pace — build the engine, no redline.",
        "intervals_easy": "Easy intervals with full recovery — groove mechanics.",
        "amrap": f"Sustainable rounds at RPE <= {rpe_cap}; leave a rep in the tank.",
        "for_time": f"Brisk but controlled; stop at the cap and keep RPE <= {rpe_cap}.",
        "intervals": "Work hard in the interval, rest fully — quality over total reps.",
        "emom": "Hit each minute's work and rest; stop if reps bleed into the next minute.",
        "benchmark": "Benchmark effort — scaled to your caps. Hydrate and monitor closely.",
    }
    return base.get(fmt, f"Keep RPE <= {rpe_cap}.")


# --- warm-up / cool-down -------------------------------------------------------
def _warmup(categories: set[str]) -> list[str]:
    t = rules.session_templates()
    out = list(t["warmup"]["general"])
    for cat in sorted(categories):
        out += t["warmup"]["specific_by_category"].get(cat, [])
    return out


def _active_recovery_plan() -> dict:
    return rules.session_templates()["active_recovery"]


# --- top level -----------------------------------------------------------------
def generate_session(state: dict, ctx: dict) -> dict:
    """state: {phase, program_week, week_in_phase, is_deload}.
    ctx: {owned_ids, checkin, last_week_vol, this_week_done, introductions, established,
          maxes, day_index}."""
    phase = state["phase"]
    phase_def = rules.phase_def(phase)
    checkin = ctx.get("checkin", {})
    owned = set(ctx.get("owned_ids", []))
    is_deload = bool(state.get("is_deload"))

    plan = {"phase": phase, "program_week": state["program_week"],
            "week_in_phase": state.get("week_in_phase", 1), "is_deload": is_deload,
            "day_index": ctx.get("day_index", 0), "notes": []}

    scr = screen.screen_redflags(checkin)
    plan["screen"] = scr
    if scr["blocked"]:
        plan.update({"blocked": True, "mode": "blocked", "warmup": [], "strength": None,
                     "wod": {"movements": []}, "cooldown": [],
                     "stimulus": scr["message"], "planned_minutes": 0})
        return plan

    plan["blocked"] = False
    scale = scaling.auto_scale(checkin, rules.phase_globals())
    plan["scale"] = scale
    plan["mode"] = scale["mode"]
    if scale["reasons"]:
        plan["notes"].append("Scaled: " + "; ".join(scale["reasons"]))

    if scale["mode"] == "active_recovery":
        ar = _active_recovery_plan()
        plan.update({"is_active_recovery": True, "warmup": [], "strength": None,
                     "wod": {"format": "active_recovery", "movements": [], "blocks": ar["blocks"],
                             "stimulus": ar["stimulus"]},
                     "cooldown": rules.session_templates()["cooldown"],
                     "stimulus": ar["stimulus"], "planned_minutes": 30})
        return plan

    factor = scale["factor"]
    maxes = ctx.get("maxes")
    strength = prescribe_strength(phase, phase_def, state["program_week"], ctx.get("day_index", 0),
                                  maxes, owned, factor, is_deload)
    wod = build_wod(phase, phase_def, state["program_week"], ctx.get("day_index", 0), owned,
                    ctx.get("introductions", {}), set(ctx.get("established", [])), factor,
                    is_deload, maxes)

    categories = set()
    if strength:
        categories.add((rules.movement_by_id(strength["movement_id"]) or {}).get("category", "barbell"))
    for mv in wod["movements"]:
        categories.add((rules.movement_by_id(mv["movement_id"]) or {}).get("category", ""))

    plan.update({"strength": strength, "wod": wod, "warmup": _warmup(categories),
                 "cooldown": rules.session_templates()["cooldown"]})

    # HARD GATE: clamp to per-session and weekly caps last of all.
    cap_notes = caps.clamp_session(plan, phase, is_deload,
                                   ctx.get("last_week_vol", {}), ctx.get("this_week_done", {}))
    plan["notes"].extend(cap_notes)

    plan["planned_minutes"] = min(phase_def["session_cap_min"],
                                  9 + (strength["sets"] * 2 if strength else 0) + wod["time_cap_min"] + 5)
    return plan
