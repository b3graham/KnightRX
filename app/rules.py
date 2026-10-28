"""Loader for the editable rule files in rules/.

The engine reads its logic from these JSON files (not the DB) so that editing a file
changes behaviour and every rule is unit-testable. Files are cached and transparently
reloaded when their mtime changes, so edits take effect without a restart.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from . import settings

_cache: dict[str, tuple[float, dict]] = {}


def _load(name: str) -> dict:
    path = os.path.join(settings.RULES_DIR, f"{name}.json")
    mtime = os.path.getmtime(path)
    cached = _cache.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    _cache[name] = (mtime, data)
    return data


# --- Raw accessors -------------------------------------------------------------
def equipment() -> list[dict]:
    return _load("equipment")["equipment"]


def movements() -> list[dict]:
    return _load("movements")["movements"]


def phases() -> list[dict]:
    return _load("phases")["phases"]


def phase_globals() -> dict:
    return _load("phases")["global"]


def safety_caps() -> dict:
    return _load("safety_caps")


def benchmarks() -> list[dict]:
    return _load("benchmarks")["benchmarks"]


def session_templates() -> dict:
    return _load("session_templates")


# --- Convenience lookups -------------------------------------------------------
def movement_by_id(mid: str) -> dict | None:
    for m in movements():
        if m["id"] == mid:
            return m
    return None


def equipment_by_id(eid: str) -> dict | None:
    for e in equipment():
        if e["id"] == eid:
            return e
    return None


def phase_def(phase: int) -> dict:
    for p in phases():
        if p["phase"] == phase:
            return p
    raise KeyError(f"no phase {phase} defined")


def phase_for_week(week: int) -> int:
    """Map an absolute program week number to its phase (last phase is open-ended)."""
    for p in phases():
        start, end = p["week_start"], p["week_end"]
        if week >= start and (end is None or week <= end):
            return p["phase"]
    return phases()[-1]["phase"]


def session_cap(cap_key: str | None, phase: int) -> int | None:
    """Per-session rep ceiling for a movement bucket at a phase; None = uncapped."""
    if not cap_key:
        return None
    table = safety_caps()["caps"].get(cap_key)
    if table is None:
        return None
    return table.get(str(phase))


def weekly_ramp_pct() -> float:
    return safety_caps()["weekly_ramp_pct"]


def deload_volume_multiplier() -> float:
    return safety_caps()["deload_volume_multiplier"]


def introduce_sessions_required() -> int:
    return safety_caps()["introduce_sessions_required"]
