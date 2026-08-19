"""
FiBand - SQLite persistence layer. Connection configured via `.env` (see config.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

from .db import connect


class Store:
    def __init__(self):
        self.conn = connect()

    def _fmt(self, ts: datetime) -> str:
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def last_sample_ts(self) -> datetime | None:
        """Timestamp (UTC) of the most recent history sample in the DB, or None if empty.
        Used for incremental sync: resumes from here instead of always downloading a
        fixed N days. Looks at the periodic-sample tables (not measurements,
        which are on-demand measurements only)."""
        tables = ("hr_samples", "step_samples", "stress_samples", "hrv_samples", "spo2_samples")
        union = " UNION ALL ".join(f"SELECT MAX(ts) AS m FROM {t}" for t in tables)
        row = self.conn.execute(f"SELECT MAX(m) FROM ({union})").fetchone()
        if not row or row[0] is None:
            return None
        return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)

    def add_measurement(self, metric: str, value: float | None, value2: float | None = None,
                        unit: str | None = None, ts: datetime | None = None) -> None:
        ts = ts or datetime.now(timezone.utc)
        self.conn.execute(
            "INSERT INTO measurements (ts, metric, value, value2, unit) VALUES (?,?,?,?,?)",
            (self._fmt(ts), metric, value, value2, unit),
        )
        self.conn.commit()

    def upsert_hr(self, samples: list[tuple[datetime, int]]) -> int:
        if not samples:
            return 0
        self.conn.executemany(
            "INSERT INTO hr_samples (ts, bpm) VALUES (?,?) "
            "ON CONFLICT(ts) DO UPDATE SET bpm=excluded.bpm",
            [(self._fmt(t), int(hr)) for t, hr in samples],
        )
        self.conn.commit()
        return len(samples)

    def upsert_steps(self, samples: list[tuple[datetime, int, int, int]]) -> int:
        if not samples:
            return 0
        self.conn.executemany(
            "INSERT INTO step_samples (ts, steps, calories, distance) VALUES (?,?,?,?) "
            "ON CONFLICT(ts) DO UPDATE SET steps=excluded.steps, calories=excluded.calories, "
            "distance=excluded.distance",
            [(self._fmt(t), int(s), int(c), int(d)) for t, s, c, d in samples],
        )
        self.conn.commit()
        return len(samples)

    def _upsert_slot(self, table: str, col: str, samples: list[tuple[datetime, int]]) -> int:
        if not samples:
            return 0
        self.conn.executemany(
            f"INSERT INTO {table} (ts, {col}) VALUES (?,?) "
            f"ON CONFLICT(ts) DO UPDATE SET {col}=excluded.{col}",
            [(self._fmt(t), int(v)) for t, v in samples],
        )
        self.conn.commit()
        return len(samples)

    def upsert_stress(self, samples: list[tuple[datetime, int]]) -> int:
        return self._upsert_slot("stress_samples", "score", samples)

    def upsert_hrv(self, samples: list[tuple[datetime, int]]) -> int:
        return self._upsert_slot("hrv_samples", "ms", samples)

    def upsert_spo2(self, samples: list[tuple[datetime, int]]) -> int:
        return self._upsert_slot("spo2_samples", "spo2", samples)

    def replace_sleep(self, sleep_date: str, segments: list[tuple[str, int]],
                      start_ts: datetime | None = None) -> int:
        """Replaces the sleep stages for a day (YYYY-MM-DD): a list of (stage, minutes).
        start_ts = sleep start instant (to position the time axis)."""
        self.conn.execute("DELETE FROM sleep_segments WHERE sleep_date=?", (sleep_date,))
        self.conn.execute("DELETE FROM sleep_sessions WHERE sleep_date=?", (sleep_date,))
        if segments:
            self.conn.executemany(
                "INSERT INTO sleep_segments (sleep_date, idx, stage, minutes) VALUES (?,?,?,?)",
                [(sleep_date, i, st, int(m)) for i, (st, m) in enumerate(segments)],
            )
        if start_ts is not None:
            self.conn.execute("INSERT INTO sleep_sessions (sleep_date, start_ts) VALUES (?,?)",
                              (sleep_date, self._fmt(start_ts)))
        self.conn.commit()
        return len(segments)

    def close(self) -> None:
        self.conn.close()
