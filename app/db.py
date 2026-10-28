"""SQLite storage. One connection per call; WAL mode so reads never block.

init() creates the schema (idempotent), runs any column migrations, seeds the movement
library and equipment from the rule files, and ensures the singleton settings/state rows
exist. The rule files remain the source of truth for movements (re-synced every start);
equipment 'owned' flags are user-editable and seeded only once.
"""
from __future__ import annotations

import json
import os
import sqlite3

from . import rules, settings

DB_PATH = settings.DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    owned INTEGER NOT NULL DEFAULT 0,
    multi_weight INTEGER NOT NULL DEFAULT 0,
    weights TEXT NOT NULL DEFAULT '[]',   -- JSON list of lb values
    unit TEXT
);

CREATE TABLE IF NOT EXISTS movements (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    equipment TEXT NOT NULL DEFAULT '[]',    -- JSON list of equipment ids
    unit TEXT NOT NULL,
    high_risk INTEGER NOT NULL DEFAULT 0,
    eccentric_heavy INTEGER NOT NULL DEFAULT 0,
    cap_key TEXT,
    min_phase INTEGER NOT NULL DEFAULT 0,
    skill_prereqs TEXT NOT NULL DEFAULT '[]',
    scaling TEXT NOT NULL DEFAULT '[]',
    substitutions TEXT NOT NULL DEFAULT '[]',
    pr_kinds TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS prs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movement_id TEXT NOT NULL REFERENCES movements(id),
    kind TEXT NOT NULL,                      -- 1RM/3RM/5RM/max_reps/max_time/test
    value REAL NOT NULL,                     -- lb, reps, seconds, cal, ... per movement unit
    unit TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'tested',   -- tested | estimated | historical
    date TEXT NOT NULL,
    source_set_id INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    phase INTEGER NOT NULL,
    program_week INTEGER NOT NULL,
    week_in_phase INTEGER NOT NULL,
    day_index INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'planned',  -- planned/completed/missed/skipped
    plan_json TEXT NOT NULL DEFAULT '{}',
    session_rpe REAL,
    is_deload INTEGER NOT NULL DEFAULT 0,
    is_active_recovery INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    movement_id TEXT NOT NULL REFERENCES movements(id),
    set_index INTEGER NOT NULL DEFAULT 0,
    weight REAL,
    reps INTEGER,
    rpe REAL,
    is_wod INTEGER NOT NULL DEFAULT 0,
    rx_or_scaled TEXT NOT NULL DEFAULT 'rx',
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wod_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    score_type TEXT NOT NULL,                -- time | rounds_reps | load | cal
    score_value TEXT NOT NULL,
    rx_or_scaled TEXT NOT NULL DEFAULT 'rx',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    when_phase TEXT NOT NULL,                -- pre | post
    sleep_hours REAL,
    soreness INTEGER,                        -- 0-10
    hydration TEXT,
    illness INTEGER NOT NULL DEFAULT 0,
    redflag_dark_urine INTEGER NOT NULL DEFAULT 0,
    redflag_pain_swelling INTEGER NOT NULL DEFAULT 0,
    redflag_weakness INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    cleared_confirmed INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS week_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_week INTEGER NOT NULL,
    phase INTEGER NOT NULL,
    decision TEXT NOT NULL,                  -- advance | repeat | deload
    reason TEXT NOT NULL,
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    training_days TEXT NOT NULL DEFAULT '{"default":["Mon","Wed","Fri"]}',
    units TEXT NOT NULL DEFAULT 'lb',
    phase_override INTEGER
);

CREATE TABLE IF NOT EXISTS crossfit_wod (
    date TEXT PRIMARY KEY,      -- ISO date of the CrossFit.com main-site WOD
    url TEXT NOT NULL,
    body TEXT NOT NULL,         -- readable workout text (reference only; not programmed)
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS program_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    phase INTEGER NOT NULL DEFAULT 0,
    program_week INTEGER NOT NULL DEFAULT 1,
    week_in_phase INTEGER NOT NULL DEFAULT 1,
    week_start TEXT,
    last_session_date TEXT,
    last_decision TEXT,
    last_decision_reason TEXT,
    started_on TEXT
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        _seed_movements(conn)
        _seed_equipment(conn)
        _ensure_singletons(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_movements(conn) -> None:
    """Movements: rule file is the source of truth — upsert every start."""
    for m in rules.movements():
        conn.execute(
            """INSERT INTO movements
               (id, name, category, equipment, unit, high_risk, eccentric_heavy,
                cap_key, min_phase, skill_prereqs, scaling, substitutions, pr_kinds)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, category=excluded.category, equipment=excluded.equipment,
                unit=excluded.unit, high_risk=excluded.high_risk,
                eccentric_heavy=excluded.eccentric_heavy, cap_key=excluded.cap_key,
                min_phase=excluded.min_phase, skill_prereqs=excluded.skill_prereqs,
                scaling=excluded.scaling, substitutions=excluded.substitutions,
                pr_kinds=excluded.pr_kinds""",
            (m["id"], m["name"], m["category"], json.dumps(m.get("equipment", [])),
             m["unit"], int(m.get("high_risk", False)), int(m.get("eccentric_heavy", False)),
             m.get("cap_key"), int(m.get("min_phase", 0)),
             json.dumps(m.get("skill_prereqs", [])), json.dumps(m.get("scaling", [])),
             json.dumps(m.get("substitutions", [])), json.dumps(m.get("pr_kinds", []))))


def _seed_equipment(conn) -> None:
    """Equipment owned-state is user-editable, so seed only when the table is empty."""
    if conn.execute("SELECT 1 FROM equipment LIMIT 1").fetchone():
        return
    for e in rules.equipment():
        conn.execute(
            """INSERT INTO equipment (id, name, category, owned, multi_weight, weights, unit)
               VALUES (?,?,?,?,?,?,?)""",
            (e["id"], e["name"], e["category"], int(e.get("owned", False)),
             int(e.get("multi_weight", False)), json.dumps(e.get("weights", [])),
             e.get("unit")))


def _ensure_singletons(conn) -> None:
    if not conn.execute("SELECT 1 FROM app_settings WHERE id=1").fetchone():
        conn.execute("INSERT INTO app_settings (id) VALUES (1)")
    if not conn.execute("SELECT 1 FROM program_state WHERE id=1").fetchone():
        from datetime import date
        conn.execute("INSERT INTO program_state (id, started_on, week_start) VALUES (1, ?, ?)",
                     (date.today().isoformat(), date.today().isoformat()))


# --- Query helpers (one fresh connection each, closed in finally) --------------
def query(sql, args=()):
    conn = connect()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def query_one(sql, args=()):
    conn = connect()
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def execute(sql, args=()):
    conn = connect()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()
