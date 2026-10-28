"""Two kinds of scaling:
1. Equipment substitution — swap a movement for one you can actually do with what you own.
2. Readiness auto-scaling — poor sleep / soreness / illness reduce the day or convert it to
   active recovery (easy bike + mobility), never a rest from the app.

Weather/heat scaling was intentionally dropped from scope.
"""
from __future__ import annotations

from .. import rules

_MAX_SUB_DEPTH = 5


def substitute_for_equipment(movement_id: str, owned_ids: set[str], _depth: int = 0) -> str | None:
    """Resolve a movement to one performable with the owned equipment, following the
    movement's ordered substitutions. Returns None if nothing resolves."""
    m = rules.movement_by_id(movement_id)
    if m is None or _depth > _MAX_SUB_DEPTH:
        return None
    if all(e in owned_ids for e in m.get("equipment", [])):
        return movement_id
    for sub in m.get("substitutions", []):
        resolved = substitute_for_equipment(sub, owned_ids, _depth + 1)
        if resolved is not None:
            return resolved
    return None


def auto_scale(checkin: dict, phase_globals: dict) -> dict:
    """Return {mode, factor, reasons}. mode in {normal, reduced, active_recovery}.
    factor multiplies strength + WOD volume (0.0 for active recovery)."""
    soreness = checkin.get("soreness") or 0
    sleep = checkin.get("sleep_hours")
    illness = bool(checkin.get("illness"))

    ar_threshold = phase_globals.get("active_recovery_if_soreness_gte", 7)

    if illness:
        return {"mode": "active_recovery", "factor": 0.0, "reasons": ["illness reported"]}
    if soreness >= ar_threshold:
        return {"mode": "active_recovery", "factor": 0.0,
                "reasons": [f"soreness {soreness}/10 — protecting recovery"]}

    factor = 1.0
    reasons: list[str] = []
    if soreness >= 5:
        factor = min(factor, 0.8)
        reasons.append(f"soreness {soreness}/10")
    if sleep is not None and sleep < 6:
        factor = min(factor, 0.8)
        reasons.append(f"short sleep {sleep}h")

    return {"mode": "reduced" if factor < 1.0 else "normal", "factor": factor, "reasons": reasons}
