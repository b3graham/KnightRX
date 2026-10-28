"""Week-to-week progression decision. Readiness gates advancement, not the calendar.

Decisions: advance | repeat | deload.
- deload every Nth week (scheduled), and also when returning from a >=7-day gap.
- repeat the week (no advance) if fewer than planned sessions were completed, average
  soreness was high, or average session RPE exceeded the phase cap.
- otherwise advance.
"""
from __future__ import annotations

from .. import rules


def decide_week(next_program_week: int, prev: dict, rpe_cap: int) -> tuple[str, str]:
    """prev: {completed, planned, avg_soreness, avg_rpe, had_gap}. next_program_week is the
    absolute week the athlete is about to enter. Returns (decision, reason)."""
    g = rules.phase_globals()

    if prev.get("had_gap"):
        return "deload", "returning from a 7+ day gap — dropping back a step before advancing"

    if next_program_week > 0 and next_program_week % g["deload_every_weeks"] == 0:
        return "deload", f"scheduled deload (every {g['deload_every_weeks']}th week)"

    reasons: list[str] = []
    completed, planned = prev.get("completed", 0), prev.get("planned", 0)
    if completed < planned:
        reasons.append(f"only {completed}/{planned} sessions completed")

    avg_sore = prev.get("avg_soreness")
    if avg_sore is not None and avg_sore >= g["repeat_if_avg_soreness_gte"]:
        reasons.append(f"average soreness {avg_sore:.0f}/10")

    avg_rpe = prev.get("avg_rpe")
    if avg_rpe is not None and avg_rpe > rpe_cap:
        reasons.append(f"average RPE {avg_rpe:.1f} over the phase cap of {rpe_cap}")

    if reasons:
        return "repeat", "repeating the week: " + "; ".join(reasons)
    return "advance", "all targets met — advancing"


def apply_decision(state: dict, decision: str) -> dict:
    """Return the next program_state given a decision. 'advance'/'deload' move forward one
    program week (deload is a lighter version of the next step); 'repeat' holds the week."""
    new = dict(state)
    if decision in ("advance", "deload"):
        new["program_week"] = state["program_week"] + 1
        new["week_in_phase"] = state["week_in_phase"] + 1
        new["phase"] = rules.phase_for_week(new["program_week"])
        # week_in_phase resets when the phase changes
        if new["phase"] != state["phase"]:
            new["week_in_phase"] = 1
    # 'repeat' leaves program_week / phase unchanged
    new["is_deload"] = (decision == "deload")
    return new
