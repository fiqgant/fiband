"""
FiBand - per-request SQLite connection (Flask `g`).

Kept separate from `app.py` and `actions.py` so both can import it without
a circular dependency (app.py registers the actions blueprint; actions.py
needs a DB connection).
"""
from __future__ import annotations

import sqlite3

from flask import g

from .db import connect


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()
