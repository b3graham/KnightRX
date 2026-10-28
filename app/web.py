"""Jinja2 environment + the page() render helper and template filters. Single user, so
there is no login context — Caddy basic auth guards the whole app in production."""
from __future__ import annotations

import os

from fastapi.templating import Jinja2Templates

from . import settings

BASE_DIR = settings.BASE_DIR
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

NAV = [
    {"href": "/", "label": "Today", "icon": "today"},
    {"href": "/calendar", "label": "Week", "icon": "week"},
    {"href": "/prs", "label": "PRs", "icon": "trophy"},
    {"href": "/history", "label": "History", "icon": "chart"},
    {"href": "/library", "label": "Movements", "icon": "book"},
    {"href": "/settings", "label": "Settings", "icon": "gear"},
]


def fmt_weight(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    return f"{int(v)} lb" if v == int(v) else f"{v:g} lb"


def fmt_pct(v) -> str:
    return "—" if v is None else f"{round(float(v) * 100)}%"


def rpe_label(v) -> str:
    return "—" if v is None else f"RPE {v:g}"


templates.env.filters["weight"] = fmt_weight
templates.env.filters["pct"] = fmt_pct
templates.env.filters["rpe"] = rpe_label
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["nav"] = NAV


def page(request, name, **ctx):
    ctx.update({"msg": request.query_params.get("msg", ""),
                "err": request.query_params.get("err", ""),
                "path": request.url.path})
    return templates.TemplateResponse(request, name, ctx)
