# Backyard Box

A single-user, mobile-first PWA that tracks your PRs and generates **progressive,
safety-capped CrossFit programming** — built for returning to training slowly and safely.

> **Not medical advice.** The app enforces conservative, rules-based guardrails, but it is
> not medical clearance. If you have a history of rhabdomyolysis or any medical condition,
> clear your return to training with a clinician. The pre/post-workout screen will **block
> all programming** if you report a warning sign (dark urine, abnormal pain/swelling,
> unusual weakness) and tell you to seek care.

## What it does

- **PR tracking** — logs sets and auto-detects PRs. Estimated 1RMs (Epley/Brzycki) are kept
  strictly separate from **tested** maxes, and pre-rhabdo numbers are **historical reference
  only** — never used to set training loads.
- **Daily programming** — a deterministic engine (no AI at runtime) builds each session:
  warm-up, one strength lift, a WOD, and a cool-down, gated by readiness and your phase.
- **Safety caps that can't be outrun** — per-session volume caps, a ≤10% weekly ramp, phase
  locks, and an "introduce a movement at low volume twice before high reps" rule. All of it
  lives in editable files and is covered by a test that proves the caps hold over 12+ weeks.
- **Readiness scaling** — a 10-second check-in (sleep, soreness, hydration, illness) scales
  the day down or converts it to active recovery.
- **Progress, calendar, weekly summary, movement library, data export, offline PWA.**

## Run locally (Windows)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8770
```

Open http://127.0.0.1:8770. The SQLite DB is created under `data/` on first run.
Run the tests (including the safety proof) with `pytest -q`.

## Deploy (Docker + Caddy basic auth)

On the VPS:

```bash
git clone <repo> backyard-box && cd backyard-box
docker compose up -d --build      # publishes 127.0.0.1:8110 only
```

Add the Caddy snippet (see `Caddyfile.example`). Generate the password hash first:

```bash
caddy hash-password --plaintext 'your-password'
```

Paste the hash into a `basic_auth` block pointing at `reverse_proxy 127.0.0.1:8110`, point a
DNS record at the VPS (Caddy auto-provisions TLS), then `systemctl reload caddy`.

The container binds to localhost only — **Caddy is the sole public entrance** and provides the
single-user login.

## Backup & restore

The database is a single file at `data/backyard.db` (a Docker volume in prod).

```bash
scripts/backup.sh                 # -> ./backups/backyard-<timestamp>.db.gz (WAL-consistent, live-safe)
```

Restore: stop the app, `gunzip -c backups/<file>.db.gz > data/backyard.db`, restart. A VPS
cron (e.g. nightly) is recommended. You can also export anytime from **Settings → Export**
(full JSON, or CSV per table).

## Editing the programming rules

All programming logic is data, in `rules/` — edit a file and the engine picks it up live (it
re-reads on change). The files:

| file | what it controls |
|---|---|
| `movements.json` | the movement library: equipment tags, risk flags, `cap_key`, `min_phase`, prerequisites, substitutions |
| `equipment.json` | the default equipment profile (also editable in Settings) |
| `phases.json` | per-phase frequency, RPE caps, WOD length/formats, strength scheme; global deload/gap rules |
| `safety_caps.json` | **the rhabdo guardrails** — per-session rep caps by movement bucket × phase, the weekly ramp %, deload multiplier |
| `benchmarks.json` | benchmark WODs and their phase locks |
| `session_templates.json` | warm-up / cool-down / active-recovery building blocks |

The cap numbers are deliberately conservative defaults. **Raise them slowly and only with good
reason** — and after running `pytest -q` to confirm the safety proof still passes.

## Layout

```
app/            FastAPI app; app/engine/ is the pure, deterministic programming engine
rules/          editable rule files (the engine's source of truth)
templates/      Jinja2 pages;  static/  CSS, JS, PWA manifest + service worker
tests/          pytest, incl. tests/test_safety.py (the 12+ week cap proof)
scripts/        backup.sh
data/           runtime SQLite DB (gitignored; Docker volume)
```
