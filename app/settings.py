"""Runtime configuration, read from the environment with repo-relative fallbacks.

No pydantic, no .env file — matches the house style of the other apps. A missing env
var just means the sensible local default is used.
"""
from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Runtime data (the SQLite DB) — gitignored locally, a Docker volume in prod.
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "backyard.db")

# Editable, committed rule files (the engine's source of truth).
RULES_DIR = os.environ.get("RULES_DIR", os.path.join(BASE_DIR, "rules"))

APP_NAME = os.environ.get("APP_NAME", "Knight RX")

# Timezone label only used for display; the app stores ISO dates.
TZ_LABEL = os.environ.get("TZ_LABEL", "America/New_York")
