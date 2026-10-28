# Knight RX

A single-user, mobile-first **PWA** that tracks personal records and generates **progressive,
safety-capped CrossFit programming** — built for returning to training slowly and safely after a
long layoff.

> **Not medical advice.** Knight RX enforces conservative, rules-based guardrails; it is **not**
> medical clearance. A pre/post-workout screen **blocks all programming** if you report a warning
> sign (dark urine, abnormal pain/swelling, unusual weakness) and directs you to seek care.

## What it does

- **PR tracking** — logs sets and auto-detects PRs. **Estimated** 1RMs (Epley / Brzycki) are kept
  strictly separate from **tested** maxes, and prior/legacy numbers are flagged **historical —
  reference only** and never used to set training loads.
- **Daily programming** — a **deterministic engine (no AI at runtime)** builds each session:
  warm-up, one strength lift, a WOD, and a cool-down, gated by readiness and your training phase.
- **Safety caps that can't be outrun** — per-session volume caps, a **≤10% weekly ramp**, phase
  locks, and an *"introduce a movement at low volume twice before high reps"* rule. All of it lives
  in editable files and is covered by a test that **proves the caps hold over 12+ weeks**.
- **Readiness scaling** — a 10-second daily check-in (sleep, soreness, hydration, illness) scales
  the day down or converts it to active recovery.
- **CrossFit.com WOD** — the official main-site Workout of the Day is shown on the Today page as a
  clearly-labeled **reference only** card — never prescribed, never safety-capped.
- **Progress & insight** — history charts, weekly summary, movement library, full data export
  (CSV/JSON), and an offline-capable PWA you can install to your phone.
- **Green-CRT terminal theme** — phosphor green on black, monospace, scanlines, built to stay
  readable outdoors.

## How it's built

| Layer | Choice |
|---|---|
| **Backend** | Python 3.12 · FastAPI |
| **Storage** | SQLite (WAL mode, one connection per request) |
| **Views** | Jinja2 server-rendered pages + vanilla JS (no build step) |
| **Offline** | PWA — web manifest + service worker caching the app shell |
| **Engine** | Pure, deterministic functions — fully unit-testable |
| **Tests** | `pytest` — 31 tests, including a 12+ week safety proof |
| **Deploy** | Docker + Docker Compose, behind a reverse proxy with HTTP basic auth and automatic HTTPS |

### The programming engine

The engine is a sequence of **hard gates**, each run in order so nothing downstream can loosen an
earlier limit:

```
red-flag screen  →  readiness scaling  →  (active recovery?)
   →  strength  →  WOD  →  equipment substitution
   →  "introduce-twice" gate  →  safety caps (LAST)
```

The safety caps run **last** by design — so no other step can ever raise volume past the ceiling.

### Everything the engine does is data

All programming logic lives in editable, version-controlled JSON under `rules/` (hot-reloaded on
change):

| file | controls |
|---|---|
| `movements.json` | the movement library: equipment tags, risk flags, phase locks, prerequisites, substitutions |
| `equipment.json` | your equipment profile (also editable in-app) |
| `phases.json` | per-phase frequency, RPE caps, WOD formats, strength schemes; global deload/gap rules |
| `safety_caps.json` | the guardrails — per-session rep caps by movement bucket × phase, the weekly ramp %, deload multiplier |
| `benchmarks.json` | benchmark WODs and their phase locks |
| `session_templates.json` | warm-up / cool-down / active-recovery building blocks |

The cap numbers are deliberately conservative defaults. **Raise them slowly and only with good
reason** — and after running `pytest -q` to confirm the safety proof still passes.

### Phases

A months-long progression from **re-entry** (low volume, RPE-capped, no max testing) →
**foundation** (linear % of estimate) → **build** (rep-max testing at phase ends, skills unlocked
by prerequisite) → **full** (benchmarks + heavier work), with a deload every 4th week throughout.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8770
```

Open http://127.0.0.1:8770. The SQLite DB is created under `data/` on first run.
Run the tests (including the safety proof) with `pytest -q`.

## Deploy

Runs as a Docker container bound to localhost, fronted by a reverse proxy that adds HTTP basic auth
and provisions TLS automatically.

```bash
docker compose up -d --build     # publishes 127.0.0.1:8110 only
```

Put it behind your reverse proxy of choice with basic auth and automatic HTTPS; the container binds
to localhost, so the proxy is the sole public entrance and provides the single-user login.

## Backup & restore

The database is a single file at `data/backyard.db` (a Docker volume in production).

```bash
scripts/backup.sh                # -> ./backups/backyard-<timestamp>.db.gz (WAL-consistent, live-safe)
```

Restore: stop the app, `gunzip -c backups/<file>.db.gz > data/backyard.db`, restart. A nightly cron
is recommended. You can also export anytime from **Settings → Export** (full JSON, or CSV per table).

## Layout

```
app/            FastAPI app; app/engine/ is the pure, deterministic engine
rules/          editable rule files (the engine's source of truth)
templates/      Jinja2 pages;  static/  CSS, JS, PWA manifest + service worker
tests/          pytest, incl. tests/test_safety.py (the 12+ week cap proof)
scripts/        backup.sh
data/           runtime SQLite DB (gitignored; Docker volume)
```
