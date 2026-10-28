#!/usr/bin/env bash
# WAL-consistent backup of the Backyard Box SQLite database. Portable: uses python3's
# sqlite3 .backup (safe to run while the app is live). Usage:
#   scripts/backup.sh [db_path] [dest_dir]
set -euo pipefail
DB="${1:-${DATA_DIR:-./data}/backyard.db}"
DEST="${2:-./backups}"
mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/backyard-$STAMP.db"
python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src); d = sqlite3.connect(dst)
with d:
    s.backup(d)
s.close(); d.close()
PY
gzip -f "$OUT"
echo "backup -> $OUT.gz"
echo "restore: stop the app, 'gunzip -c <file>.gz > data/backyard.db', restart."
