"""PR tracking: estimated-1RM math, auto-detection from logged sets, and the hard
separation between tested, estimated, and historical (pre-rhabdo) maxes.

Rules that matter for safety:
- A logged working set never becomes a *tested* 1RM. From sets we only ever derive an
  *estimated* 1RM (clearly labelled). Tested maxes come from an explicit test action.
- Pre-rhabdo numbers are stored source='historical' and are NEVER returned to the engine
  for programming — see programming_max(), which excludes them.
"""
from __future__ import annotations

from datetime import date

from . import db, rules

# Rep count above which a single-set 1RM estimate is too unreliable to trust.
_EST_REP_CEILING = 12


def epley(weight: float, reps: int) -> float:
    return weight * (1 + reps / 30.0)


def brzycki(weight: float, reps: int) -> float:
    return weight * 36.0 / (37.0 - reps)


def estimate_1rm(weight: float, reps: int, method: str = "epley") -> float:
    """Estimated 1RM from a rep set. reps==1 returns the weight; reps are clamped to a
    sane ceiling so a high-rep set can't produce a wild estimate."""
    if weight <= 0 or reps < 1:
        return 0.0
    if reps == 1:
        return float(weight)
    reps = min(reps, _EST_REP_CEILING)
    return brzycki(weight, reps) if method == "brzycki" else epley(weight, reps)


def best_value(movement_id: str, kinds: tuple[str, ...],
               exclude_historical: bool = True, sources: tuple[str, ...] | None = None) -> float | None:
    clause = "movement_id = ? AND kind IN (%s)" % ",".join("?" * len(kinds))
    args: list = [movement_id, *kinds]
    if exclude_historical:
        clause += " AND source != 'historical'"
    if sources:
        clause += " AND source IN (%s)" % ",".join("?" * len(sources))
        args += list(sources)
    row = db.query_one(f"SELECT MAX(value) AS v FROM prs WHERE {clause}", tuple(args))
    return row["v"] if row and row["v"] is not None else None


def programming_max(movement_id: str) -> float | None:
    """The 1RM the ENGINE may use for percentages: best non-historical max, preferring a
    tested max over an estimate. Returns None when nothing usable exists yet (early phases)."""
    tested = best_value(movement_id, ("1RM",), sources=("tested",))
    if tested is not None:
        return tested
    return best_value(movement_id, ("1RM",), sources=("estimated",))


def detect_from_set(movement: dict, weight: float | None, reps: int | None) -> list[dict]:
    """Return any new PRs implied by a logged set (not yet written)."""
    out: list[dict] = []
    pr_kinds = movement.get("pr_kinds", [])
    mid = movement["id"]

    if weight and reps and any(k in pr_kinds for k in ("1RM", "3RM", "5RM")):
        est = round(estimate_1rm(weight, reps), 1)
        best = best_value(mid, ("1RM",))  # tested or estimated, excluding historical
        if est > 0 and (best is None or est > best + 1e-6):
            out.append({"kind": "1RM", "value": est, "unit": "lb", "source": "estimated"})

    if reps and "max_reps" in pr_kinds:
        best = best_value(mid, ("max_reps",))
        if best is None or reps > best:
            out.append({"kind": "max_reps", "value": float(reps), "unit": "reps", "source": "tested"})

    return out


def record_prs(movement_id: str, prs: list[dict], on: str | None = None,
               source_set_id: int | None = None) -> list[int]:
    on = on or date.today().isoformat()
    ids = []
    for pr in prs:
        ids.append(db.execute(
            """INSERT INTO prs (movement_id, kind, value, unit, source, date, source_set_id, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (movement_id, pr["kind"], pr["value"], pr["unit"], pr.get("source", "tested"),
             on, source_set_id, pr.get("notes"))))
    return ids


def log_tested_max(movement_id: str, kind: str, value: float, on: str | None = None) -> int:
    """Explicit tested max (e.g. a Phase-2 rep-max test). source='tested'."""
    unit = "lb" if kind in ("1RM", "3RM", "5RM") else (rules.movement_by_id(movement_id) or {}).get("unit", "reps")
    return record_prs(movement_id, [{"kind": kind, "value": value, "unit": unit, "source": "tested"}], on=on)[0]


def log_historical(movement_id: str, kind: str, value: float, on: str | None = None) -> int:
    """Pre-rhabdo reference number. source='historical' — reference only, never programmed."""
    unit = "lb" if kind in ("1RM", "3RM", "5RM") else (rules.movement_by_id(movement_id) or {}).get("unit", "reps")
    return record_prs(movement_id, [{"kind": kind, "value": value, "unit": unit,
                                     "source": "historical", "notes": "pre-rhabdo reference"}], on=on)[0]
