"""
FiBand - dashboard data loader.

Resolves the selected period, loads every series the dashboard templates
need, computes the period stats (current vs previous, equal-length windows)
and the last saved AI report, then returns a single dict consumed by the
Flask routes via `render_template(**dashboard_data(...))`. Pure data:
templates contain no queries.

SQLite has no `CONVERT_TZ`: local-day grouping (which MySQL did in SQL) is
done here in Python via `zoneinfo`, on rows fetched in the already-needed
UTC-range queries.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import FIBAND_TZ

TZL = ZoneInfo(FIBAND_TZ)
UTC = timezone.utc

RANGES = {"today": "Today", "24h": "Last 24h", "7d": "7 days", "30d": "30 days", "custom": "Custom"}


def _utc_str(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _local_date(ts: str) -> str:
    """UTC DB timestamp string -> local calendar date (YYYY-MM-DD)."""
    return _parse_utc(ts).astimezone(TZL).strftime("%Y-%m-%d")


def _subtract_months(dt: datetime, months: int) -> datetime:
    month = dt.month - months
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    days_in_month = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, days_in_month[month - 1])
    return dt.replace(year=year, month=month, day=day)


def period_stat(conn: sqlite3.Connection, table: str, col: str,
                cur_from: str, cur_to: str, prev_from: str, prev_to: str) -> dict:
    """Stats for one samples table over two explicit windows (current vs previous),
    returning the delta as a percentage of the previous average."""
    def q(frm: str, to: str) -> dict:
        row = conn.execute(
            f"SELECT AVG({col}) a, MIN({col}) mn, MAX({col}) mx, COUNT(*) c "
            f"FROM {table} WHERE ts >= ? AND ts < ?", (frm, to)).fetchone()
        return {
            "avg": float(row["a"]) if row["a"] is not None else None,
            "min": float(row["mn"]) if row["mn"] is not None else None,
            "max": float(row["mx"]) if row["mx"] is not None else None,
            "n": int(row["c"]),
        }
    cur = q(cur_from, cur_to)
    prev = q(prev_from, prev_to)
    delta = None
    if cur["avg"] is not None and prev["avg"]:
        delta = round((cur["avg"] - prev["avg"]) / prev["avg"] * 100, 1)
    return {**cur, "delta_pct": delta}


def dashboard_data(conn: sqlite3.Connection, args) -> dict:
    """Loads everything the dashboard templates need for the current request.
    `args` is a mapping with `.get()` (Flask's `request.args`)."""
    # ---------- Selected period ----------
    range_ = args.get("range") if args.get("range") in RANGES else "24h"
    now = datetime.now(UTC)
    start: str
    end: str | None = None
    if range_ == "today":
        d = datetime.now(TZL).replace(hour=0, minute=0, second=0, microsecond=0)
        start = _utc_str(d)
    elif range_ == "7d":
        start = _utc_str(now - timedelta(days=7))
    elif range_ == "30d":
        start = _utc_str(now - timedelta(days=30))
    elif range_ == "custom":
        try:
            f = datetime.strptime(args.get("from", ""), "%Y-%m-%d").replace(tzinfo=TZL)
        except ValueError:
            f = datetime.now(TZL)
        try:
            t = datetime.strptime(args.get("to", ""), "%Y-%m-%d").replace(tzinfo=TZL)
        except ValueError:
            t = datetime.now(TZL)
        f = f.replace(hour=0, minute=0, second=0, microsecond=0)
        t = t.replace(hour=23, minute=59, second=59, microsecond=0)
        start = _utc_str(f)
        end = _utc_str(t)
    else:  # '24h' / default
        start = _utc_str(now - timedelta(hours=24))

    where_cond = "ts >= ? AND ts <= ?" if end else "ts >= ?"
    cond_params: list = [start, end] if end else [start]

    long_range = range_ not in ("today", "24h")
    custom_from = args.get("from") or datetime.now(TZL).strftime("%Y-%m-%d")
    custom_to = args.get("to") or datetime.now(TZL).strftime("%Y-%m-%d")
    pl = RANGES[range_]

    # ---------- Data loading ----------
    err = None
    latest: dict = {}
    hr: list = []
    steps: list = []
    steps_by_day: list = []
    recent: list = []
    stress_hist: list = []
    hrv: list = []
    allrows: list = []
    spo2hist: list = []
    sleep_segs: list = []
    sleep_date = None
    sleep_start = None
    sleep_days: dict = {}
    sleep_period_total = 0
    latest_stress = None
    latest_hrv = None
    latest_spo2 = None
    series = {"spo2": [], "blood_pressure": []}
    days_with_data: dict = {}
    day_notes: dict = {}

    try:
        rows = conn.execute(
            f"SELECT m.metric, m.value, m.value2, m.unit, m.ts FROM measurements m "
            f"JOIN (SELECT metric, MAX(id) id FROM measurements WHERE {where_cond} GROUP BY metric) x "
            f"ON m.id = x.id", cond_params).fetchall()
        for r in rows:
            latest[r["metric"]] = dict(r)
        rows_all = conn.execute(
            "SELECT m.metric, m.value, m.value2, m.unit, m.ts FROM measurements m "
            "JOIN (SELECT metric, MAX(id) id FROM measurements GROUP BY metric) x "
            "ON m.id = x.id").fetchall()
        for r in rows_all:
            latest.setdefault(r["metric"], dict(r))

        hr = [dict(r) for r in conn.execute(
            f"SELECT ts, bpm FROM hr_samples WHERE {where_cond} ORDER BY ts", cond_params)]
        steps = [dict(r) for r in conn.execute(
            f"SELECT ts, steps FROM step_samples WHERE {where_cond} ORDER BY ts", cond_params)]
        stress_hist = [dict(r) for r in conn.execute(
            f"SELECT ts, score FROM stress_samples WHERE {where_cond} ORDER BY ts", cond_params)]
        hrv = [dict(r) for r in conn.execute(
            f"SELECT ts, ms FROM hrv_samples WHERE {where_cond} ORDER BY ts", cond_params)]
        spo2hist = [dict(r) for r in conn.execute(
            f"SELECT ts, spo2 FROM spo2_samples WHERE {where_cond} ORDER BY ts", cond_params)]

        # Steps summed per local day: used by the chart when the period spans multiple days.
        day_sums: dict[str, int] = {}
        for r in steps:
            d = _local_date(r["ts"])
            day_sums[d] = day_sums.get(d, 0) + r["steps"]
        steps_by_day = [{"d": d, "s": s} for d, s in sorted(day_sums.items())]

        # latest sample of each sensor in the period, falling back to the all-time latest
        def latest_val(table: str, col: str):
            row = conn.execute(
                f"SELECT {col} v FROM {table} WHERE {where_cond} ORDER BY ts DESC LIMIT 1",
                cond_params).fetchone()
            if row is None:
                row = conn.execute(f"SELECT {col} v FROM {table} ORDER BY ts DESC LIMIT 1").fetchone()
            return row["v"] if row is not None else None

        latest_stress = latest_val("stress_samples", "score")
        latest_hrv = latest_val("hrv_samples", "ms")
        latest_spo2 = latest_val("spo2_samples", "spo2")

        # sleep: latest available day (stages are per-day, not per-period)
        row = conn.execute("SELECT MAX(sleep_date) d FROM sleep_segments").fetchone()
        sleep_date = row["d"] if row else None
        if sleep_date:
            sleep_segs = [dict(r) for r in conn.execute(
                "SELECT idx, stage, minutes FROM sleep_segments WHERE sleep_date=? ORDER BY idx",
                (sleep_date,))]
            srow = conn.execute(
                "SELECT start_ts FROM sleep_sessions WHERE sleep_date=?", (sleep_date,)).fetchone()
            sleep_start = srow["start_ts"] if srow else None

        # sleep: all nights in the selected period, for the day-by-day check.
        # sleep_date is a local date; map the UTC range boundaries to local dates.
        start_dt = _parse_utc(start)
        sleep_from = start_dt.astimezone(TZL).strftime("%Y-%m-%d")
        end_dt_for_sleep = _parse_utc(end) if end else datetime.now(UTC)
        sleep_to = end_dt_for_sleep.astimezone(TZL).strftime("%Y-%m-%d")
        for r in conn.execute(
                "SELECT s.sleep_date d, s.idx, s.stage, s.minutes, ss.start_ts "
                "FROM sleep_segments s LEFT JOIN sleep_sessions ss ON ss.sleep_date = s.sleep_date "
                "WHERE s.sleep_date BETWEEN ? AND ? ORDER BY s.sleep_date, s.idx",
                (sleep_from, sleep_to)):
            d = r["d"]
            if d not in sleep_days:
                sleep_days[d] = {"date": d, "start": r["start_ts"], "segs": []}
            sleep_days[d]["segs"].append({"idx": r["idx"], "stage": r["stage"], "minutes": r["minutes"]})
            sleep_period_total += int(r["minutes"])

        for metric in list(series.keys()):
            rows = conn.execute(
                f"SELECT ts, value, value2 FROM measurements WHERE metric = ? AND {where_cond} ORDER BY ts",
                [metric] + cond_params).fetchall()
            series[metric] = [dict(r) for r in rows]

        recent = [dict(r) for r in conn.execute(
            "SELECT ts, metric, value, value2, unit FROM measurements ORDER BY id DESC LIMIT 30")]

        # single table: all data saved (history + measurements) for the period, most recent first
        allrows_sql = (
            f"SELECT ts, 'Heart Rate' tipo, bpm v1, NULL v2, NULL v3, 'bpm' unit FROM hr_samples WHERE {where_cond} "
            f"UNION ALL SELECT ts, 'Steps', steps, calories, distance, 'steps' FROM step_samples WHERE {where_cond} "
            f"UNION ALL SELECT ts, 'Stress', score, NULL, NULL, '' FROM stress_samples WHERE {where_cond} "
            f"UNION ALL SELECT ts, 'HRV', ms, NULL, NULL, 'ms' FROM hrv_samples WHERE {where_cond} "
            f"UNION ALL SELECT ts, metric, value, value2, NULL, unit FROM measurements WHERE {where_cond} "
            f"ORDER BY ts DESC LIMIT 1000"
        )
        allrows = [dict(r) for r in conn.execute(allrows_sql, cond_params * 5)]

        # ----- Diary: days with at least one data point (last 6 months) + personal notes -----
        # Independent of the period selected above: the diary feeds the AI analysis (6 months).
        note_start_utc = _utc_str(_subtract_months(datetime.now(UTC), 6))
        note_start_date = _subtract_months(datetime.now(TZL), 6).strftime("%Y-%m-%d")
        for tbl, lbl in [("hr_samples", "Heart Rate"), ("step_samples", "Steps"),
                          ("stress_samples", "Stress"), ("hrv_samples", "HRV"),
                          ("spo2_samples", "SpO2"), ("measurements", "Measurements")]:
            seen: set[str] = set()
            for r in conn.execute(f"SELECT ts FROM {tbl} WHERE ts >= ?", (note_start_utc,)):
                d = _local_date(r["ts"])
                if d not in seen:
                    days_with_data.setdefault(d, []).append(lbl)
                    seen.add(d)
        for r in conn.execute(
                "SELECT DISTINCT sleep_date d FROM sleep_segments WHERE sleep_date >= ?", (note_start_date,)):
            days_with_data.setdefault(r["d"], []).append("Sleep")
        days_with_data = dict(sorted(days_with_data.items(), reverse=True))  # most recent days first
        day_notes = {r["note_date"]: r["note"] for r in conn.execute("SELECT note_date, note FROM day_notes")}
    except Exception as e:
        err = str(e)

    # ---------- Period stats (selected period vs the previous period of equal length) ----------
    empty = {"avg": None, "min": None, "max": None, "n": 0, "delta_pct": None}
    weekly = {"hr": empty, "spo2": empty, "stress": empty, "hrv": empty}
    week_steps = {"total": 0, "daily_avg": 0, "best_day": None, "best_day_steps": 0, "delta_pct": None}
    week_sleep = {"avg_min": None, "delta_pct": None}
    streak = 0
    try:
        start_dt = _parse_utc(start)
        end_dt = _parse_utc(end) if end else datetime.now(UTC)
        dur = (end_dt - start_dt).total_seconds() or 86400
        prev_start_dt = start_dt - timedelta(seconds=dur)
        prev_start = _utc_str(prev_start_dt)
        prev_end = start
        cur_end = _utc_str(end_dt)

        weekly["hr"] = period_stat(conn, "hr_samples", "bpm", start, cur_end, prev_start, prev_end)
        weekly["spo2"] = period_stat(conn, "spo2_samples", "spo2", start, cur_end, prev_start, prev_end)
        weekly["stress"] = period_stat(conn, "stress_samples", "score", start, cur_end, prev_start, prev_end)
        weekly["hrv"] = period_stat(conn, "hrv_samples", "ms", start, cur_end, prev_start, prev_end)

        def sum_steps(frm: str, to: str) -> int:
            row = conn.execute(
                "SELECT COALESCE(SUM(steps),0) s FROM step_samples WHERE ts >= ? AND ts < ?",
                (frm, to)).fetchone()
            return int(row["s"])

        cur_steps = sum_steps(start, cur_end)
        prev_steps = sum_steps(prev_start, prev_end)

        day_sums2: dict[str, int] = {}
        for r in conn.execute(
                "SELECT ts, steps FROM step_samples WHERE ts >= ? AND ts < ?", (start, cur_end)):
            d = _local_date(r["ts"])
            day_sums2[d] = day_sums2.get(d, 0) + r["steps"]
        best_day = None
        best_day_steps = 0
        if day_sums2:
            best_day, best_day_steps = max(day_sums2.items(), key=lambda kv: kv[1])

        days_n = max(1, round(dur / 86400))
        week_steps = {
            "total": cur_steps,
            "daily_avg": round(cur_steps / days_n),
            "best_day": best_day,
            "best_day_steps": best_day_steps,
            "delta_pct": round((cur_steps - prev_steps) / prev_steps * 100, 1) if prev_steps else None,
        }

        def sleep_avg(frm_date: str, to_date: str) -> float | None:
            rows = conn.execute(
                "SELECT SUM(minutes) m FROM sleep_segments WHERE sleep_date >= ? AND sleep_date < ? "
                "GROUP BY sleep_date", (frm_date, to_date)).fetchall()
            vals = [r["m"] for r in rows]
            return sum(vals) / len(vals) if vals else None

        cur_from_d = start_dt.astimezone(TZL).strftime("%Y-%m-%d")
        cur_to_d = end_dt.astimezone(TZL).strftime("%Y-%m-%d")
        prev_from_d = prev_start_dt.astimezone(TZL).strftime("%Y-%m-%d")
        prev_to_d = _parse_utc(prev_end).astimezone(TZL).strftime("%Y-%m-%d")
        cur_sleep = sleep_avg(cur_from_d, cur_to_d)
        prev_sleep = sleep_avg(prev_from_d, prev_to_d)
        week_sleep = {
            "avg_min": cur_sleep,
            "delta_pct": (round((cur_sleep - prev_sleep) / prev_sleep * 100, 1)
                          if cur_sleep is not None and prev_sleep else None),
        }

        # active streak: consecutive local days (today backwards) with at least one data point
        cursor = datetime.now(TZL)
        while cursor.strftime("%Y-%m-%d") in days_with_data:
            streak += 1
            cursor -= timedelta(days=1)
    except Exception:
        pass  # period stats stay at defaults

    # last saved AI report (separate try: the table might be empty)
    last_report = None
    try:
        row = conn.execute(
            "SELECT ts, model, report_short, report, report_diet, tokens_in, tokens_out "
            "FROM ai_report ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            last_report = dict(row)
    except Exception:
        pass

    return {
        "RANGES": RANGES, "range": range_, "TZL": TZL, "now": now,
        "start": start, "end": end, "longRange": long_range,
        "custom_from": custom_from, "custom_to": custom_to, "pl": pl,
        "err": err, "latest": latest, "hr": hr, "steps": steps, "stepsByDay": steps_by_day,
        "recent": recent, "stressHist": stress_hist, "hrv": hrv, "allrows": allrows,
        "spo2hist": spo2hist, "sleepSegs": sleep_segs, "sleepDate": sleep_date,
        "sleepStart": sleep_start, "sleepDays": sleep_days, "sleepPeriodTotal": sleep_period_total,
        "latestStress": latest_stress, "latestHrv": latest_hrv, "latestSpo2": latest_spo2,
        "series": series, "daysWithData": days_with_data, "dayNotes": day_notes,
        "weekly": weekly, "weekSteps": week_steps, "weekSleep": week_sleep, "streak": streak,
        "lastReport": last_report,
    }
