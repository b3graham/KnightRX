"""The CrossFit.com reference-WOD fetcher: HTML extraction, caching, and graceful failure.

No network: the live fetch is monkeypatched so the suite stays deterministic and offline-safe.
"""
from datetime import date

from fastapi.testclient import TestClient

from app import crossfit_wod, db
from app.main import app

SAMPLE_PAGE = """
<html><head><title>CrossFit Workout of the Day 261028</title></head>
<body>
<main><article>
  <div class="_count_x">20</div>
  <p>Complete as many rounds and reps as possible in 9 minutes of:</p>
  <p>3 handstand walk squares</p>
  <p>9 toes-to-bars</p>
  <p>Post rounds and reps to comments.</p>
  <h3>Intermediate option:</h3>
  <p>1 handstand walk around a box</p>
  <p>9 knees-to-chests</p>
  <h3>Resources:</h3>
  <a href="#">The Handstand Walk Square</a>
  <p>Find a gym near you:</p>
</article></main>
</body></html>
"""


def test_extract_pulls_workout_and_trims_boilerplate():
    body = crossfit_wod._extract(SAMPLE_PAGE)
    assert body is not None
    assert "9 minutes" in body
    assert "handstand walk squares" in body
    assert "Intermediate option" in body
    # trailing demo-video links / gym boilerplate are cut
    assert "Resources" not in body
    assert "Find a gym" not in body


def test_extract_returns_none_without_article():
    assert crossfit_wod._extract("<html><body>no article here</body></html>") is None


def test_get_caches_success_and_serves_from_db(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(on):
        calls["n"] += 1
        return {"ok": True, "date": on.isoformat(),
                "url": "https://www.crossfit.com/workout/x", "body": "3 rounds for time"}

    monkeypatch.setattr(crossfit_wod, "fetch", fake_fetch)
    on = date(2026, 10, 28)

    first = crossfit_wod.get(on)
    assert first["ok"] and first["body"] == "3 rounds for time"
    assert db.query_one("SELECT * FROM crossfit_wod WHERE date=?", (on.isoformat(),)) is not None

    second = crossfit_wod.get(on)        # served from cache, no second fetch
    assert second.get("cached") is True
    assert calls["n"] == 1


def test_get_does_not_cache_failure(monkeypatch):
    monkeypatch.setattr(crossfit_wod, "fetch",
                        lambda on: {"ok": False, "date": on.isoformat(),
                                    "url": "u", "error": "offline"})
    on = date(2026, 10, 28)
    res = crossfit_wod.get(on)
    assert res["ok"] is False
    assert db.query_one("SELECT * FROM crossfit_wod WHERE date=?", (on.isoformat(),)) is None


def test_api_route_returns_json(monkeypatch):
    monkeypatch.setattr(crossfit_wod, "get",
                        lambda on=None: {"ok": True, "date": "2026-10-28",
                                         "url": "u", "body": "AMRAP 9", "cached": False})
    with TestClient(app) as c:
        r = c.get("/api/crossfit-wod")
        assert r.status_code == 200
        assert r.json()["body"] == "AMRAP 9"
