"""Fetch the official CrossFit.com main-site Workout of the Day (reference only).

This is the *classic*, uncapped CrossFit.com programming. It is shown on the Today page
purely as reading/reference — it is NOT what the engine prescribes and is NOT safety-capped.
The programmed session (built by app/engine) is always the one to follow.

The page is fetched with a plain HTTP GET (the workout is server-rendered inside a single
<article> element) and cached in SQLite so crossfit.com is hit at most once per day. All
failures are soft: callers get {"ok": False, ...} and the Today page degrades gracefully
(important for offline backyard use).
"""
from __future__ import annotations

import re
from datetime import date, datetime

import httpx

from . import db

WORKOUT_URL = "https://www.crossfit.com/workout/{y:04d}/{m:02d}/{d:02d}"
PAGE_URL = "https://www.crossfit.com/workout/{y:04d}/{m:02d}/{d:02d}"
_UA = "Mozilla/5.0 (Backyard Box; reference WOD fetch)"
_TIMEOUT = 6.0

# Where the readable workout stops and site boilerplate / demo-video links begin.
_TRIM_MARKERS = ("Resources:", "Find a gym", "Comments", "Compare to", "Post your")


def _url(on: date) -> str:
    return PAGE_URL.format(y=on.year, m=on.month, d=on.day)


def _extract(html_text: str) -> str | None:
    """Pull the readable workout text out of the page's single <article> element."""
    m = re.search(r"<article\b[^>]*>(.*?)</article>", html_text, re.S | re.I)
    if not m:
        return None
    body = m.group(1)
    body = re.sub(r"<(script|style|svg|button)\b.*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r"</(p|div|li|h[1-6])>", "\n", body, flags=re.I)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    text = re.sub(r"<[^>]+>", "", body)
    text = _unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    # Cut trailing resource links / site boilerplate.
    cut = len(text)
    for marker in _TRIM_MARKERS:
        i = text.find(marker)
        if i != -1:
            cut = min(cut, i)
    text = text[:cut].strip()
    return text or None


def _unescape(s: str) -> str:
    import html as _html
    return _html.unescape(s)


def fetch(on: date) -> dict:
    """Live-fetch and parse a day's WOD. Returns a result dict; never raises."""
    url = _url(on)
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT,
                      follow_redirects=True)
        r.raise_for_status()
        body = _extract(r.text)
        if not body:
            return {"ok": False, "date": on.isoformat(), "url": url,
                    "error": "Could not read the workout from the page."}
        return {"ok": True, "date": on.isoformat(), "url": url, "body": body}
    except Exception as exc:  # network down, timeout, HTTP error, parse miss
        return {"ok": False, "date": on.isoformat(), "url": url,
                "error": f"Couldn't reach crossfit.com ({type(exc).__name__})."}


def get(on: date | None = None) -> dict:
    """Cached accessor: serve from SQLite if we already have the day, else fetch once.

    Only successful fetches are cached, so a failure (e.g. offline) is retried next visit.
    """
    on = on or date.today()
    iso = on.isoformat()
    row = db.query_one("SELECT * FROM crossfit_wod WHERE date=?", (iso,))
    if row is not None:
        return {"ok": True, "date": iso, "url": row["url"], "body": row["body"],
                "fetched_at": row["fetched_at"], "cached": True}

    result = fetch(on)
    if result.get("ok"):
        db.execute(
            """INSERT INTO crossfit_wod (date, url, body, fetched_at)
               VALUES (?,?,?,?)
               ON CONFLICT(date) DO UPDATE SET url=excluded.url, body=excluded.body,
                                               fetched_at=excluded.fetched_at""",
            (iso, result["url"], result["body"], datetime.now().isoformat(timespec="seconds")))
    return result
