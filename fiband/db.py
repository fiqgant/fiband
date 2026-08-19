"""
FiBand - SQLite persistence (replaces the old MySQL/MariaDB database).

Tables:
  measurements   -> on-demand measurements (heart rate, SpO2, blood pressure, stress) with timestamp
  hr_samples     -> historical heart-rate curve (1 point / 5 min), unique ts
  step_samples   -> historical steps/calories/distance (1 point / 15 min), unique ts
  stress_samples -> historical stress curve (1 point / 30 min), unique ts
  hrv_samples    -> historical HRV curve (ms, 1 point / 30 min), unique ts
  spo2_samples   -> historical SpO2 curve (1 point / hour), unique ts
  sleep_segments -> per-night sleep stage breakdown (light/deep/rem/awake)
  sleep_sessions -> per-night sleep start instant
  day_notes      -> user's personal notes for a single local day
  ai_report      -> saved AI analysis reports (OpenRouter)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import DB_PATH, FIBAND_TZ

_TZL = ZoneInfo(FIBAND_TZ)

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS measurements (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        metric  TEXT NOT NULL,
        value   REAL,
        value2  REAL,
        unit    TEXT,
        source  TEXT DEFAULT 'H59'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_measurements_metric ON measurements(metric)",
    "CREATE INDEX IF NOT EXISTS idx_measurements_ts ON measurements(ts)",
    """CREATE TABLE IF NOT EXISTS hr_samples (
        ts   TEXT NOT NULL PRIMARY KEY,
        bpm  INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS step_samples (
        ts        TEXT NOT NULL PRIMARY KEY,
        steps     INTEGER NOT NULL,
        calories  INTEGER,
        distance  INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS stress_samples (
        ts     TEXT NOT NULL PRIMARY KEY,
        score  INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS hrv_samples (
        ts   TEXT NOT NULL PRIMARY KEY,
        ms   INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS spo2_samples (
        ts    TEXT NOT NULL PRIMARY KEY,
        spo2  INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sleep_segments (
        sleep_date  TEXT NOT NULL,
        idx         INTEGER NOT NULL,
        stage       TEXT NOT NULL,
        minutes     INTEGER NOT NULL,
        PRIMARY KEY (sleep_date, idx)
    )""",
    """CREATE TABLE IF NOT EXISTS sleep_sessions (
        sleep_date  TEXT NOT NULL PRIMARY KEY,
        start_ts    TEXT NOT NULL
    )""",
    # User's personal notes for a single day (e.g. "10km run in the afternoon",
    # "vacation at the beach"): qualitative context passed to the AI analysis. One per local day.
    """CREATE TABLE IF NOT EXISTS day_notes (
        note_date   TEXT NOT NULL PRIMARY KEY,
        note        TEXT,
        updated_at  TEXT NOT NULL
    )""",
    # AI analysis reports (generated via OpenRouter):
    # report_short = quick analysis, report = full analysis, report_diet = dietary advice
    """CREATE TABLE IF NOT EXISTS ai_report (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT NOT NULL,
        model         TEXT,
        days          INTEGER,
        prompt        TEXT,
        report_short  TEXT,
        report        TEXT,
        report_diet   TEXT,
        tokens_in     INTEGER,
        tokens_out    INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_report_ts ON ai_report(ts)",
]


def _local_date(ts: str | None) -> str | None:
    """SQL function: UTC DB timestamp string -> local calendar date (YYYY-MM-DD).
    Replaces MySQL's CONVERT_TZ() for local-day grouping (used by the AI-prompt
    aggregation queries, which rely on SQLite's window functions like PERCENT_RANK)."""
    if ts is None:
        return None
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone(_TZL).strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    """Opens a SQLite connection (schema ensured, dict-like row access)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("local_date", 1, _local_date, deterministic=True)
    for ddl in SCHEMA:
        conn.execute(ddl)
    conn.commit()
    return conn
