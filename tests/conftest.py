"""Each test gets a fresh temp SQLite DB, seeded from the real rule files."""
import importlib

import pytest


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from app import settings as app_settings
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(app_settings, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_settings, "DB_PATH", str(db_path))

    from app import db
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    db.init()
    yield db
