"""
FiBand - one-time data migration: old MySQL/MariaDB database -> new SQLite file.

Run once, after installing the new requirements, to carry over existing
history (HR/steps/sleep/notes/AI reports) collected under the old PHP+MySQL
stack into the new all-Python Flask+SQLite app. Not part of the app's
runtime path; safe to delete afterwards.

Needs `pymysql` (not in requirements.txt anymore -- install it just for
this one run: `.venv/bin/pip install pymysql`), and the OLD MySQL
connection settings still present in `.env` (DB_HOST/DB_PORT/DB_NAME/
DB_USER/DB_PASS) at the time you run it.

Usage:
    .venv/bin/pip install pymysql
    .venv/bin/python migrate_mysql_to_sqlite.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_env(ROOT_DIR / ".env")

try:
    import pymysql
except ImportError:
    print("pymysql not installed. Run: .venv/bin/pip install pymysql", file=sys.stderr)
    sys.exit(1)

from fiband.db import SCHEMA, connect  # noqa: E402

MYSQL_CONFIG = dict(
    host=os.environ.get("DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("DB_PORT", "3306")),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASS", ""),
    database=os.environ.get("DB_NAME", "fiband"),
)

TABLES = [
    "measurements", "hr_samples", "step_samples", "stress_samples", "hrv_samples",
    "spo2_samples", "sleep_segments", "sleep_sessions", "day_notes", "ai_report",
]


def main() -> None:
    print(f"Connecting to old MySQL database {MYSQL_CONFIG['database']!r} "
          f"at {MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}...")
    my_conn = pymysql.connect(**MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)

    sqlite_conn = connect()   # creates fiband.db + schema if missing

    for table in TABLES:
        with my_conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table}")
            rows = cur.fetchall()
        if not rows:
            print(f"  {table}: 0 rows (skipped)")
            continue

        cols = [c for c in rows[0].keys() if c != "id"]   # let SQLite assign its own AUTOINCREMENT id
        placeholders = ",".join("?" for _ in cols)
        col_list = ",".join(cols)
        sql = f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})"

        values = [tuple(str(r[c]) if r[c] is not None else None for c in cols) for r in rows]
        sqlite_conn.executemany(sql, values)
        sqlite_conn.commit()

        count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {len(rows)} rows migrated (SQLite now has {count} total)")

    my_conn.close()
    sqlite_conn.close()
    print("Done. Verify row counts above, then start the app with: python app.py")


if __name__ == "__main__":
    main()
