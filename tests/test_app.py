"""End-to-end web tests via TestClient: the Today flow, PR detection, chart API, exports,
and that the red-flag check-in blocks programming."""
import json

from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_pages_render():
    with TestClient(app) as c:
        for u in ["/", "/calendar", "/prs", "/history", "/library", "/settings"]:
            assert c.get(u).status_code == 200, u


def test_red_flag_checkin_blocks():
    with TestClient(app) as c:
        c.post("/today/checkin", data={"soreness": "3", "sleep_hours": "7", "redflag_dark_urine": "1"})
        assert "Training blocked" in c.get("/").text
        # no session was created
        assert db.query_one("SELECT COUNT(*) n FROM sessions")["n"] == 0


def test_full_flow_generates_logs_pr_and_completes():
    with TestClient(app) as c:
        c.post("/today/checkin", data={"soreness": "2", "sleep_hours": "8", "hydration": "ok"})
        sess = db.query_one("SELECT * FROM sessions ORDER BY id DESC LIMIT 1")
        assert sess is not None
        plan = json.loads(sess["plan_json"])
        move = plan["strength"]["movement_id"]

        r = c.post("/today/log-set", follow_redirects=False, data={
            "session_id": sess["id"], "movement_id": move, "weight": "135", "reps": "5",
            "rpe": "6", "is_wod": "0", "rx": "rx"})
        assert "New+PR" in r.headers.get("location", "")

        pr = db.query_one("SELECT * FROM prs WHERE movement_id=?", (move,))
        assert pr["source"] == "estimated"  # a logged set yields an estimate, never a tested max

        c.post("/today/complete", data={"session_id": sess["id"], "session_rpe": "6"})
        assert db.query_one("SELECT status FROM sessions WHERE id=?", (sess["id"],))["status"] == "completed"

        # chart API + exports
        assert c.get(f"/api/history?movement={move}").json()["series"]
        assert c.get("/export/all.json").status_code == 200
        assert c.get("/export/prs.csv").text.startswith("id,movement_id,kind")
