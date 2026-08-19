"""
FiBand - AJAX actions: /action/sync, /action/save_note, /action/ai_prompt.

Replaces src/actions/*.php. `sync` used to shell out to `collect.py` as a
subprocess (PHP's `exec()`); here it calls `fiband.collect.run()` directly
in-process via `asyncio.run()`.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from . import collect
from .config import BAND_ADDRESS, FIBAND_TZ, OPENROUTER_MODEL, ROOT_DIR
from .helpers import clean_ai_html, json_fix_ctrl, openrouter_chat
from .webdb import get_db

bp = Blueprint("actions", __name__, url_prefix="/action")


@bp.route("/sync", methods=["POST"])
def sync():
    mode = request.args.get("mode")
    if mode not in ("quick", "full", "history"):
        mode = "quick"
    try:
        result = asyncio.run(collect.run(BAND_ADDRESS, mode, None, None))
    except Exception as e:
        return jsonify({"ok": False, "errors": [str(e)]})
    return jsonify(result)


@bp.route("/save_note", methods=["POST"])
def save_note():
    try:
        date_str = request.form.get("date", "")
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            d = None
        if d is None or d.strftime("%Y-%m-%d") != date_str:
            raise RuntimeError("Invalid date")
        note = request.form.get("note", "").strip()[:2000]   # cap: don't bloat the prompt
        conn = get_db()
        if note == "":
            conn.execute("DELETE FROM day_notes WHERE note_date=?", (date_str,))
        else:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO day_notes (note_date, note, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(note_date) DO UPDATE SET note=excluded.note, updated_at=excluded.updated_at",
                (date_str, note, now))
        conn.commit()
        return jsonify({"ok": True, "date": date_str, "has": note != "", "note": note})
    except Exception as e:
        return jsonify({"ok": False, "errors": [str(e)]})


def _num(v) -> str:
    if v is None:
        return ""
    return f"{float(v):.1f}".rstrip("0").rstrip(".")


def _salvage_fields(content: str) -> dict | None:
    """Best-effort field extraction when the model's JSON is malformed (a
    literal unescaped quote or stray control char inside a value breaks
    strict parsing, which weaker/free models do fairly often here). Splits
    on the literal `"key":` markers themselves instead of relying on the
    value content being valid JSON, since the keys are fixed by our prompt
    and reliable even when the values around them aren't."""
    keys = ["quick_analysis", "full_analysis", "dietary_advice"]
    marker_pos = {k: content.find(f'"{k}"') for k in keys}
    if marker_pos["quick_analysis"] == -1 or marker_pos["full_analysis"] == -1:
        return None

    def _slice(key: str, next_key: str | None) -> str:
        start = content.find(":", marker_pos[key]) + 1
        end = marker_pos.get(next_key, -1) if next_key else -1
        raw = (content[start:end] if end != -1 else content[start:]).strip()
        raw = raw.rstrip(",").rstrip()
        if raw.endswith("}"):
            raw = raw[:-1].rstrip()
        if raw.startswith('"'):
            raw = raw[1:]
        if raw.endswith('"'):
            raw = raw[:-1]
        return raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")

    return {
        "quick_analysis": _slice("quick_analysis", "full_analysis"),
        "full_analysis": _slice("full_analysis", "dietary_advice" if marker_pos["dietary_advice"] != -1 else None),
        "dietary_advice": _slice("dietary_advice", None) if marker_pos["dietary_advice"] != -1 else "",
    }


def _subtract_months(dt: datetime, months: int) -> datetime:
    month = dt.month - months
    year = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    days_in_month = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, days_in_month[month - 1])
    return dt.replace(year=year, month=month, day=day)


@bp.route("/ai_prompt", methods=["POST"])
def ai_prompt():
    from zoneinfo import ZoneInfo
    tzl = ZoneInfo(FIBAND_TZ)
    try:
        conn = get_db()
        start_utc = _subtract_months(datetime.now(timezone.utc), 6).strftime("%Y-%m-%d %H:%M:%S")
        start_date = _subtract_months(datetime.now(tzl), 6).strftime("%Y-%m-%d")

        days: dict[str, dict] = {}

        def put(d, key, val):
            days.setdefault(d, {})[key] = val

        # Heart rate: daily min/max robust to the 5th/95th percentile, so a single
        # sensor glitch (e.g. one isolated 40 bpm sample) doesn't define the day's
        # extremes. Below 12 samples the day is unreliable -> use raw MIN/MAX instead.
        for r in conn.execute(
            "SELECT d, ROUND(AVG(bpm)) a, "
            "ROUND(CASE WHEN COUNT(*) >= 12 THEN MIN(CASE WHEN pr >= 0.05 THEN bpm END) ELSE MIN(bpm) END) mn, "
            "ROUND(CASE WHEN COUNT(*) >= 12 THEN MAX(CASE WHEN pr <= 0.95 THEN bpm END) ELSE MAX(bpm) END) mx "
            "FROM (SELECT local_date(ts) d, bpm, "
            "PERCENT_RANK() OVER (PARTITION BY local_date(ts) ORDER BY bpm) pr FROM hr_samples WHERE ts >= ?) s "
            "GROUP BY d", (start_utc,)):
            put(r["d"], "hr", dict(r))
        # SpO2: reports the minimum (alert value), but robust to the 5th percentile to
        # discard single dips caused by poor sensor contact.
        for r in conn.execute(
            "SELECT d, ROUND(AVG(spo2),1) a, "
            "ROUND(CASE WHEN COUNT(*) >= 12 THEN MIN(CASE WHEN pr >= 0.05 THEN spo2 END) ELSE MIN(spo2) END) mn "
            "FROM (SELECT local_date(ts) d, spo2, "
            "PERCENT_RANK() OVER (PARTITION BY local_date(ts) ORDER BY spo2) pr FROM spo2_samples WHERE ts >= ?) s "
            "GROUP BY d", (start_utc,)):
            put(r["d"], "spo2", dict(r))
        # Stress: reports the peak, robust to the 95th percentile to discard single spurious spikes.
        for r in conn.execute(
            "SELECT d, ROUND(AVG(score)) a, "
            "ROUND(CASE WHEN COUNT(*) >= 12 THEN MAX(CASE WHEN pr <= 0.95 THEN score END) ELSE MAX(score) END) mx "
            "FROM (SELECT local_date(ts) d, score, "
            "PERCENT_RANK() OVER (PARTITION BY local_date(ts) ORDER BY score) pr FROM stress_samples WHERE ts >= ?) s "
            "GROUP BY d", (start_utc,)):
            put(r["d"], "stress", dict(r))
        for r in conn.execute(
            "SELECT local_date(ts) d, ROUND(AVG(ms)) a FROM hrv_samples WHERE ts >= ? GROUP BY d", (start_utc,)):
            put(r["d"], "hrv", dict(r))
        for r in conn.execute(
            "SELECT local_date(ts) d, SUM(steps) steps, SUM(calories) cal, SUM(distance) dist "
            "FROM step_samples WHERE ts >= ? GROUP BY d", (start_utc,)):
            put(r["d"], "steps", dict(r))
        for r in conn.execute(
            "SELECT local_date(ts) d, ROUND(AVG(value)) sys, ROUND(AVG(value2)) dia FROM measurements "
            "WHERE metric='blood_pressure' AND ts >= ? GROUP BY d", (start_utc,)):
            put(r["d"], "bp", dict(r))

        # Sleep: sleep_date is already a local date; sum the minutes for each stage.
        for r in conn.execute(
            "SELECT sleep_date d, stage, SUM(minutes) m FROM sleep_segments WHERE sleep_date >= ? "
            "GROUP BY sleep_date, stage", (start_date,)):
            d = r["d"]
            sl = days.setdefault(d, {}).setdefault("sleep", {"light": 0, "deep": 0, "rem": 0, "awake": 0, "total": 0})
            sl[r["stage"]] = int(r["m"])
            sl["total"] += int(r["m"])

        days = dict(sorted(days.items()))

        # Personal notes written by the user for individual days (qualitative context).
        user_notes: dict[str, str] = {}
        for r in conn.execute(
            "SELECT note_date, note FROM day_notes WHERE note_date >= ? ORDER BY note_date", (start_date,)):
            n = re.sub(r"\s+", " ", (r["note"] or "")).strip()
            if n:
                user_notes[r["note_date"]] = n

        # Helpers for the yearly stats and the CSV cells.
        def col(grp, key):
            return [float(d[grp][key]) for d in days.values() if grp in d and d[grp].get(key) is not None]

        def avg(a):
            return _num(sum(a) / len(a)) if a else "—"

        def mn(a):
            return _num(min(a)) if a else "—"

        def mx(a):
            return _num(max(a)) if a else "—"

        def sum_(a):
            return _num(sum(a)) if a else "—"

        def g(row, grp, key):
            v = row.get(grp, {}).get(key) if grp in row else None
            return _num(v) if v is not None else ""

        first = next(iter(days), "—")
        last = next(reversed(days), "—") if days else "—"
        sleep_totals_col = col("sleep", "total")

        # ----- Prompt construction -----
        p = []
        p.append("YOU ARE A DOCTOR AND HEALTH DATA ANALYST.\n\n")
        p.append("Analyze the health data collected by a fitness band (model H59) for a single user over the last 6 months. Evaluate the data exclusively from a health standpoint.\n\n")
        p.append("== INSTRUCTIONS ==\n")
        p.append("1. Summarize the overall health status that emerges from the data.\n")
        p.append("2. Identify trends over time (improvements or declines) for each metric.\n")
        p.append("3. Flag anomalous values or potential warning signs (e.g. low SpO2, elevated resting heart rate, declining HRV, insufficient sleep, high blood pressure), distinguishing PERSISTENT anomalies from isolated values that may be sensor artifacts (see DATA QUALITY NOTE).\n")
        p.append("4. Highlight possible correlations between metrics (e.g. high stress ↔ low HRV ↔ poor sleep).\n")
        p.append("5. Provide practical, personalized advice to improve these parameters.\n")
        p.append("6. Clearly indicate when it would be advisable to consult a doctor.\n")
        p.append("7. Take into account the PERSONAL NOTES written by the user (dedicated section below): use them to interpret the observed values (e.g. physical activity, travel, diet, stress, illness) and to make the analysis and advice more relevant to their real life. Distinguish what is explained by a note (expected) from what remains unexplained (worth investigating).\n")
        p.append("Respond in English, in a way that is clear and understandable even to a non-expert.\n")
        p.append("IMPORTANT: this is an informational analysis and does NOT replace medical advice.\n\n")
        p.append("== RESPONSE FORMAT ==\n")
        p.append("Respond EXCLUSIVELY with a valid JSON object (no text outside the JSON, no ``` fences), with exactly these three keys:\n")
        p.append('{"quick_analysis": "...", "full_analysis": "...", "dietary_advice": "..."}\n')
        p.append('- "quick_analysis": a CONCISE summary (max ~120 words) with the 2-4 most important points and any warning signs.\n')
        p.append('- "full_analysis": a detailed analysis covering all 6 points from the instructions above.\n')
        p.append('- "dietary_advice": practical dietary advice and possible supplements, based SPECIFICALLY on this user\'s data (e.g. HRV, stress, sleep, heart rate, physical activity). For each food/supplement, briefly explain its purpose in relation to the observed data. Remember that supplements should only be taken after consulting a doctor and do not replace a balanced diet.\n')
        p.append("The value of ALL three keys must be vanilla HTML (no Markdown), using only these tags: <h3>, <h4>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <br>, <table>, <thead>, <tbody>, <tr>, <th>, <td>.\n")
        p.append("In the full analysis, use <h3> for each section and <table> for numeric comparisons.\n")
        p.append("Do NOT include inline CSS, style attributes, the tags <html>/<head>/<body>/<style>/<script>, images, or external links.\n")
        p.append("Escape any quotes inside the HTML as required by the JSON format. All text in English.\n\n")
        p.append("== METRICS AND UNITS ==\n")
        p.append("- Heart rate (HR): beats per minute (bpm). Typical resting range 60-100.\n")
        p.append("- SpO2: blood oxygen saturation (%). Normal >= 95%.\n")
        p.append("- Stress: index 0-100 (higher = more stress).\n")
        p.append("- HRV: heart rate variability (ms). Higher = generally better.\n")
        p.append("- Steps / Calories (kcal) / Distance (m): daily physical activity.\n")
        p.append("- Sleep: total minutes and breakdown by stage (light, deep, REM, awake).\n")
        p.append("- Blood pressure (BP): systolic/diastolic (mmHg). Reference ~120/80.\n\n")
        p.append("== DATA QUALITY NOTE ==\n")
        p.append("The data comes from a wrist-worn optical sensor (H59) that can occasionally produce ISOLATED erroneous readings (momentary non-physiological dips or spikes). To limit their effect, the daily min/max values reported here are NOT the absolute daily minimum/maximum but the 5th/95th percentile: so hr_min ≈ resting heart rate and hr_max ≈ peak under exertion, already cleaned of individual glitches.\n")
        p.append("As a result:\n")
        p.append("- Treat as reliable mainly the PERSISTENT or RECURRING anomalies (over multiple hours or days), not single out-of-range values.\n")
        p.append("- If a value appears clinically implausible and is not confirmed by context (nearby days, other correlated metrics), treat it as a likely sensor artifact and flag it as such, without asserting it as certain or raising an alarm based on it alone.\n\n")
        p.append("== PERIOD SUMMARY ==\n")
        p.append(f"Range: from {first} to {last} — {len(days)} days with data.\n")
        p.append(f"Heart rate: average {avg(col('hr','a'))} bpm (daily min {mn(col('hr','mn'))}, peak {mx(col('hr','mx'))}).\n")
        p.append(f"SpO2: average {avg(col('spo2','a'))}% (minimum {mn(col('spo2','mn'))}%).\n")
        p.append(f"Stress: average {avg(col('stress','a'))} (peak {mx(col('stress','mx'))}).\n")
        p.append(f"HRV: average {avg(col('hrv','a'))} ms.\n")
        p.append(f"Steps: total {sum_(col('steps','steps'))}, average {avg(col('steps','steps'))}/day.\n")
        p.append(f"Blood pressure: average {avg(col('bp','sys'))}/{avg(col('bp','dia'))} mmHg.\n")
        sleep_avg_min = (sum(sleep_totals_col) / len(sleep_totals_col)) if sleep_totals_col else None
        p.append("Sleep: average " + (f"{round(sleep_avg_min / 60, 1)}h" if sleep_avg_min is not None else "—")
                  + f" per night ({len(sleep_totals_col)} nights recorded).\n\n")

        # Daily data on TWO levels: full detail on the last 7 days (for actionable
        # advice) and a concise recap of the previous months (for trends). The
        # recent 7 days are EXCLUDED from the recap to avoid duplicating the same days.
        cut7 = (datetime.now(tzl) - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = {d: row for d, row in days.items() if d > cut7}
        older = {d: row for d, row in days.items() if d <= cut7}

        p.append("The daily data is on TWO levels: the LAST 7 DAYS in full detail (use these for actionable advice) and the PREVIOUS MONTHS as a concise recap (use this for long-term trends). The recent 7 days are NOT repeated in the recap.\n\n")

        p.append("== LAST 7 DAYS (detail, CSV) ==\n")
        p.append("date,hr_avg,hr_min,hr_max,spo2_avg,spo2_min,stress_avg,stress_max,hrv_avg,steps,kcal,dist_m,sleep_tot_min,sleep_light,sleep_deep,sleep_rem,sleep_awake,bp_sys,bp_dia\n")
        for d, row in recent.items():
            sl = row.get("sleep")
            cells = [
                d,
                g(row, "hr", "a"), g(row, "hr", "mn"), g(row, "hr", "mx"),
                g(row, "spo2", "a"), g(row, "spo2", "mn"),
                g(row, "stress", "a"), g(row, "stress", "mx"),
                g(row, "hrv", "a"),
                g(row, "steps", "steps"), g(row, "steps", "cal"), g(row, "steps", "dist"),
                str(sl["total"]) if sl else "", str(sl["light"]) if sl else "",
                str(sl["deep"]) if sl else "", str(sl["rem"]) if sl else "", str(sl["awake"]) if sl else "",
                g(row, "bp", "sys"), g(row, "bp", "dia"),
            ]
            p.append(",".join(cells) + "\n")
        if not recent:
            p.append("(no data in the last 7 days)\n")

        p.append("\n== PREVIOUS MONTHS (daily recap, CSV) ==\n")
        p.append("date,hr_avg,hr_min,hr_max,spo2_avg,spo2_min,stress_avg,hrv_avg,steps,sleep_tot_min\n")
        for d, row in older.items():
            sl = row.get("sleep")
            cells = [
                d,
                g(row, "hr", "a"), g(row, "hr", "mn"), g(row, "hr", "mx"),
                g(row, "spo2", "a"), g(row, "spo2", "mn"),
                g(row, "stress", "a"),
                g(row, "hrv", "a"),
                g(row, "steps", "steps"),
                str(sl["total"]) if sl else "",
            ]
            p.append(",".join(cells) + "\n")
        if not older:
            p.append("(no data in the previous months)\n")

        p.append("\n== USER'S PERSONAL NOTES (qualitative context) ==\n")
        p.append("Notes written by the user to explain what happened on certain days or time windows (physical activity, events, travel, diet, illness...). These are NOT clinical data but real-world context: use them to interpret the numbers and personalize advice and flags (e.g. many steps and a high heart rate on a day noted \"run\" are expected; poor sleep noted \"travel\" is not a warning sign). Format: one line per day, \"date: note\".\n")
        if user_notes:
            for d, n in user_notes.items():
                p.append(f"{d}: {n}\n")
        else:
            p.append("(no notes entered by the user)\n")

        p.append("== END OF DATA ==\n\nNow proceed with the health analysis following the instructions above.\n")

        prompt = "".join(p)
        try:
            (ROOT_DIR / "prompt.txt").write_text(prompt)   # debug copy of the sent prompt
        except OSError:
            pass

        ai = openrouter_chat(prompt, True)
        content = re.sub(r'^```[a-zA-Z]*\s*', '', ai["content"].strip())
        content = re.sub(r'\s*```$', '', content)
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            try:
                parsed = json.loads(json_fix_ctrl(content))
            except ValueError:
                parsed = None
        if not isinstance(parsed, dict) or "quick_analysis" not in parsed or "full_analysis" not in parsed:
            parsed = _salvage_fields(content)  # last resort: extract by key position, not strict JSON
        if isinstance(parsed, dict) and "quick_analysis" in parsed and "full_analysis" in parsed:
            short = clean_ai_html(str(parsed["quick_analysis"]))
            full = clean_ai_html(str(parsed["full_analysis"]))
            diet = clean_ai_html(str(parsed.get("dietary_advice") or ""))
        else:
            full = clean_ai_html(content)
            short = full
            diet = ""

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "INSERT INTO ai_report (ts, model, days, prompt, report_short, report, report_diet, tokens_in, tokens_out) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (now_str, OPENROUTER_MODEL, len(days), prompt, short, full, diet, ai["tokens_in"], ai["tokens_out"]))
        conn.commit()
        return jsonify({
            "ok": True,
            "id": cur.lastrowid,
            "model": OPENROUTER_MODEL,
            "days": len(days),
            "tokens_in": ai["tokens_in"],
            "tokens_out": ai["tokens_out"],
            "short": short,
            "full": full,
            "diet": diet,
        })
    except Exception as e:
        return jsonify({"ok": False, "errors": [str(e)]})
