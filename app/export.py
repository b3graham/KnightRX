"""Data export — CSV per table and a full JSON dump. Your data, portable, any time."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter
from fastapi.responses import Response

from . import db

router = APIRouter()

_TABLES = ["prs", "sessions", "sets", "wod_scores", "checkins", "week_decisions"]


def _csv_response(name: str, rows) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    if rows:
        writer.writerow(rows[0].keys())
        writer.writerows([list(r) for r in rows])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export/{table}.csv")
async def export_csv(table: str):
    if table not in _TABLES:
        return Response("unknown table", status_code=404)
    return _csv_response(f"backyard-{table}.csv", db.query(f"SELECT * FROM {table} ORDER BY id"))


@router.get("/export/all.json")
async def export_json():
    data = {t: [dict(r) for r in db.query(f"SELECT * FROM {t} ORDER BY id")] for t in _TABLES}
    data["equipment"] = [dict(r) for r in db.query("SELECT * FROM equipment")]
    data["program_state"] = dict(db.query_one("SELECT * FROM program_state WHERE id=1"))
    body = json.dumps(data, indent=2, default=str)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="backyard-export.json"'})
