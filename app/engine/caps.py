"""Volume-cap enforcement — the rhabdo safety core.

Two ceilings, both read from safety_caps.json, both inviolable:
- Per-session cap: total reps of a movement bucket (cap_key) in one session, counting
  BOTH the strength piece and the WOD. Reduced on deload weeks.
- Weekly ramp: a bucket's total weekly volume may not exceed last week's by more than
  weekly_ramp_pct. The ramp does not restrict the first week a bucket is used (you cannot
  ramp up from zero), so the per-session cap governs the baseline.

clamp_session mutates the plan's WOD movements down to fit and returns human-readable
notes. Strength is never clamped here (phase schemes keep it under cap by design); it is
counted first so the WOD only gets the remainder.
"""
from __future__ import annotations

import math
from collections import defaultdict

from .. import rules


def session_cap_for(cap_key: str | None, phase: int, is_deload: bool) -> int | None:
    cap = rules.session_cap(cap_key, phase)
    if cap is None:
        return None
    if is_deload:
        cap = math.floor(cap * rules.deload_volume_multiplier())
    return cap


def _strength_usage(plan: dict) -> dict[str, int]:
    usage: dict[str, int] = defaultdict(int)
    st = plan.get("strength")
    if st and st.get("cap_key"):
        usage[st["cap_key"]] += int(st.get("planned_total", 0))
    return usage


def session_cap_usage(plan: dict) -> dict[str, int]:
    """Total prescribed reps per cap_key in this plan (strength + WOD). This is what the
    per-session cap governs."""
    usage = _strength_usage(plan)
    for mv in plan.get("wod", {}).get("movements", []):
        if mv.get("cap_key"):
            usage[mv["cap_key"]] += int(mv.get("planned_total", 0))
    return dict(usage)


def wod_usage(plan: dict) -> dict[str, int]:
    """Prescribed WOD reps per cap_key (strength excluded). This is what the weekly ramp
    governs — strength follows its own phase scheme, not the conditioning ramp."""
    usage: dict[str, int] = defaultdict(int)
    for mv in plan.get("wod", {}).get("movements", []):
        if mv.get("cap_key"):
            usage[mv["cap_key"]] += int(mv.get("planned_total", 0))
    return dict(usage)


def clamp_session(plan: dict, phase: int, is_deload: bool,
                  last_week_vol: dict[str, int], this_week_done: dict[str, int]) -> list[str]:
    """Clamp the plan's WOD so no per-session cap or weekly ramp is exceeded. Returns notes."""
    ramp_mult = 1.0 + rules.weekly_ramp_pct()
    notes: list[str] = []

    # Per-session budget counts strength first (strength is never clamped here).
    sess_usage = _strength_usage(plan)
    # Weekly-ramp budget counts WOD volume only (strength has its own phase scheme).
    wod_used: dict[str, int] = defaultdict(int)

    def weekly_cap(k: str) -> float | None:
        lw = last_week_vol.get(k, 0)
        if lw <= 0:
            return None  # bootstrapping week: ramp does not bind
        return math.floor(lw * ramp_mult)

    kept = []
    for mv in plan.get("wod", {}).get("movements", []):
        k = mv.get("cap_key")
        rps = max(1, int(mv.get("reps_per_set", mv.get("planned_total", 1)) or 1))
        planned = int(mv.get("planned_total", 0))

        if not k:
            kept.append(mv)
            continue

        sess_cap = session_cap_for(k, phase, is_deload)
        budget = planned
        if sess_cap is not None:
            budget = min(budget, sess_cap - sess_usage.get(k, 0))
        wk = weekly_cap(k)
        if wk is not None:
            budget = min(budget, wk - this_week_done.get(k, 0) - wod_used.get(k, 0))
        budget = max(0, budget)

        if budget >= planned:
            sess_usage[k] = sess_usage.get(k, 0) + planned
            wod_used[k] += planned
            kept.append(mv)
            continue

        if budget <= 0:
            notes.append(f"{mv['name']}: dropped (at {k} cap for this session/week)")
            continue

        # Trim to a whole number of sets where possible, else a single short set.
        trimmed = (budget // rps) * rps or budget
        mv["planned_total"] = trimmed
        if trimmed < rps:
            mv["reps_per_set"] = trimmed
        mv["scaled_note"] = f"trimmed to {trimmed} (from {planned}) for {k} safety cap"
        notes.append(f"{mv['name']}: {planned}->{trimmed} reps ({k} cap)")
        sess_usage[k] = sess_usage.get(k, 0) + trimmed
        wod_used[k] += trimmed
        kept.append(mv)

    if "wod" in plan:
        plan["wod"]["movements"] = kept
    return notes
