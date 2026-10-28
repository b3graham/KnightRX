"""Unit tests for the engine's individual decision functions."""
from app import rules
from app.engine import caps, progression, scaling, screen

OWNED = {e["id"] for e in rules.equipment() if e.get("owned")}


# --- equipment substitution ----------------------------------------------------
def test_substitution_resolves_to_owned():
    assert scaling.substitute_for_equipment("back_squat", OWNED) == "back_squat"   # owned as-is
    assert scaling.substitute_for_equipment("run", OWNED) == "bike"                # no track -> bike
    assert scaling.substitute_for_equipment("row", OWNED) == "bike"                # no rower -> bike
    assert scaling.substitute_for_equipment("box_jump", OWNED) == "walking_lunge"  # no box/rings chain
    assert scaling.substitute_for_equipment("bench_press", OWNED) == "pushup"      # no bench -> push-up


def test_substitution_returns_none_when_nothing_resolves():
    assert scaling.substitute_for_equipment("ring_row", set()) is None


# --- readiness auto-scale ------------------------------------------------------
def test_auto_scale_states():
    g = rules.phase_globals()
    assert scaling.auto_scale({"soreness": 2, "sleep_hours": 8}, g)["mode"] == "normal"
    assert scaling.auto_scale({"soreness": 5, "sleep_hours": 8}, g)["mode"] == "reduced"
    assert scaling.auto_scale({"soreness": 2, "sleep_hours": 5}, g)["factor"] == 0.8
    assert scaling.auto_scale({"soreness": 8}, g)["mode"] == "active_recovery"
    assert scaling.auto_scale({"illness": True, "soreness": 1}, g)["mode"] == "active_recovery"


# --- caps ----------------------------------------------------------------------
def test_session_cap_and_deload():
    assert caps.session_cap_for("pullups", 0, False) == 0
    assert caps.session_cap_for("air_squats", 0, False) == 50
    assert caps.session_cap_for("air_squats", 0, True) == 30     # deload 0.6 * 50


def test_clamp_trims_wod_to_session_cap():
    # Phase 0 air-squat cap is 50; ask for 90 and expect a trim to <= 50.
    plan = {"strength": None, "wod": {"movements": [
        {"movement_id": "air_squat", "name": "Air Squat", "cap_key": "air_squats",
         "reps_per_set": 15, "planned_total": 90}]}}
    notes = caps.clamp_session(plan, 0, False, {}, {})
    total = plan["wod"]["movements"][0]["planned_total"]
    assert total <= 50 and notes


def test_clamp_counts_strength_against_session_cap():
    # Strength uses 25 of the squats_loaded cap (phase 1 cap 40); a 40-rep goblet WOD
    # must be trimmed to the remaining 15.
    plan = {"strength": {"cap_key": "squats_loaded", "planned_total": 25},
            "wod": {"movements": [
                {"movement_id": "kb_goblet_squat", "name": "Goblet", "cap_key": "squats_loaded",
                 "reps_per_set": 10, "planned_total": 40}]}}
    caps.clamp_session(plan, 1, False, {}, {})
    assert caps.session_cap_usage(plan)["squats_loaded"] <= 40


def test_clamp_enforces_weekly_ramp():
    # Last week did 30 kb swings; this week's ramp ceiling is floor(30*1.1)=33.
    plan = {"strength": None, "wod": {"movements": [
        {"movement_id": "kb_swing", "name": "KB Swing", "cap_key": "kb_swings",
         "reps_per_set": 12, "planned_total": 48}]}}
    caps.clamp_session(plan, 1, False, {"kb_swings": 30}, {})
    assert plan["wod"]["movements"][0]["planned_total"] <= 33


# --- progression ---------------------------------------------------------------
def test_decide_week_scheduled_deload():
    d, _ = progression.decide_week(4, {"completed": 3, "planned": 3, "avg_soreness": 2,
                                        "avg_rpe": 5, "had_gap": False}, 6)
    assert d == "deload"


def test_decide_week_gap_steps_back():
    d, r = progression.decide_week(5, {"completed": 3, "planned": 3, "avg_soreness": 2,
                                       "avg_rpe": 5, "had_gap": True}, 7)
    assert d == "deload" and "gap" in r


def test_decide_week_repeats_on_poor_week():
    d, r = progression.decide_week(5, {"completed": 1, "planned": 3, "avg_soreness": 8,
                                       "avg_rpe": 9, "had_gap": False}, 7)
    assert d == "repeat"


def test_decide_week_advances_when_clean():
    d, _ = progression.decide_week(6, {"completed": 3, "planned": 3, "avg_soreness": 2,
                                       "avg_rpe": 6, "had_gap": False}, 7)
    assert d == "advance"


def test_apply_decision_moves_phase_on_week_boundary():
    # Week 4 -> advancing into week 5 crosses from phase 0 into phase 1.
    state = {"phase": 0, "program_week": 4, "week_in_phase": 4, "is_deload": False}
    new = progression.apply_decision(state, "advance")
    assert new["program_week"] == 5 and new["phase"] == 1 and new["week_in_phase"] == 1
