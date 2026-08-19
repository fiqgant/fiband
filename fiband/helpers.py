"""
FiBand - shared helper functions.

All formatting, timezone conversion, sleep rendering and OpenRouter plumbing
lives here so templates stay readable and app.py stays thin.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from markupsafe import Markup, escape

from .config import FIBAND_TZ, OPENROUTER_API_KEY, OPENROUTER_MODEL

TZL = ZoneInfo(FIBAND_TZ)
UTC = timezone.utc

# ---------------------------------------------------------------------------
# AI: OpenRouter call
# ---------------------------------------------------------------------------


def clean_ai_html(s: str) -> str:
    """Cleans up the HTML produced by the model before saving/displaying it:
    strips any Markdown fences, the document wrapper, and unsafe tags/attributes."""
    s = s.strip()
    s = re.sub(r'^```[a-zA-Z]*\s*', '', s)   # leading ```html
    s = re.sub(r'\s*```$', '', s)            # trailing ```
    m = re.search(r'<body[^>]*>(.*)</body>', s, re.IGNORECASE | re.DOTALL)
    if m:
        s = m.group(1)                       # keep only the body
    s = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r'''\son\w+\s*=\s*("[^"]*"|'[^']*')''', '', s, flags=re.IGNORECASE)
    return s.strip()


def json_fix_ctrl(s: str) -> str:
    """Some models (e.g. DeepSeek) insert *literal* newline/tab/CR characters inside JSON
    string values instead of escaping them (\\n, \\t, \\r): the standard forbids this and
    json.loads fails. Here we re-escape them, but ONLY while inside a string, leaving
    the structure untouched. Safe on UTF-8: we only act on ASCII control bytes."""
    out: list[str] = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch); esc = False; continue
            if ch == '\\':
                out.append(ch); esc = True; continue
            if ch == '"':
                out.append(ch); in_str = False; continue
            if ch == '\n':
                out.append('\\n'); continue
            if ch == '\r':
                out.append('\\r'); continue
            if ch == '\t':
                out.append('\\t'); continue
            out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return ''.join(out)


def openrouter_chat(prompt: str, json_mode: bool = False) -> dict:
    """Calls the OpenRouter chat completion API."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY missing: add it to the .env file")
    body: dict = {"model": OPENROUTER_MODEL, "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=body, timeout=300,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://127.0.0.1:8080",
                "X-Title": "FiBand",
            },
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Network error contacting OpenRouter: {e}")
    try:
        j = resp.json()
    except ValueError:
        j = {}
    if resp.status_code != 200:
        msg = (j.get("error") or {}).get("message") if isinstance(j, dict) else None
        raise RuntimeError(f"OpenRouter returned an error: {msg or f'HTTP {resp.status_code}'}")
    choices = j.get("choices") or []
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    if not content:
        raise RuntimeError("Empty response from OpenRouter")
    usage = j.get("usage") or {}
    return {"content": content, "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens")}

# ---------------------------------------------------------------------------
# Timezone helpers (timestamps are stored in UTC, displayed in the local TZ)
# ---------------------------------------------------------------------------


def _to_local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).replace(tzinfo=UTC).astimezone(TZL)


def tlabel(ts: str, long: bool = False) -> str:
    """UTC timestamp from the DB -> local label (e.g. "14:05" or "17/08 14:05")."""
    d = _to_local(ts)
    return d.strftime("%d/%m %H:%M") if long else d.strftime("%H:%M")


def tlocal(ts: str) -> str:
    """UTC timestamp from the DB -> full local date and time."""
    return _to_local(ts).strftime("%d/%m/%Y %H:%M:%S")

# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------


def card_val(latest: dict, key: str, suffix: str = "") -> str:
    if key not in latest:
        return "—"
    r = latest[key]
    if key == "blood_pressure":
        return f'{int(r["value"])}/{int(r["value2"])}'
    n = f'{float(r["value"]):.1f}'.rstrip('0').rstrip('.')
    return n + suffix


_TIPO_LABELS = {"heart_rate": "Heart Rate", "blood_pressure": "Blood Pressure", "spo2": "SpO2",
                "stress": "Stress", "battery": "Battery"}


def tipo_label(t: str | None) -> str:
    """Display label for the data type (the on-demand metrics are already in English in the DB)."""
    if t is None:
        return ""
    return _TIPO_LABELS.get(t, str(t))


def sleep_totals(segs: list[dict]) -> dict:
    """Sleep totals per stage (minutes) from a list of segments."""
    t = {"light": 0, "deep": 0, "rem": 0, "awake": 0, "total": 0}
    for s in segs:
        t[s["stage"]] = t.get(s["stage"], 0) + int(s["minutes"])
        t["total"] += int(s["minutes"])
    return t


def hhmm(minutes: int) -> str:
    """Minutes -> "Xh YYm"."""
    return f"{minutes // 60}h {minutes % 60:02d}m"


def sleep_panel_body(segs: list[dict], start_ts: str | None, tzl: ZoneInfo) -> Markup:
    """Sleep panel body (totals + hypnogram + time axis + stats) for a SINGLE night."""
    tot = sleep_totals(segs)
    axis_start = axis_end = None
    ticks: list[tuple[float, str]] = []
    if start_ts and tot["total"]:
        axis_start = datetime.fromisoformat(start_ts).replace(tzinfo=UTC).astimezone(tzl)
        axis_end = axis_start + timedelta(minutes=tot["total"])
        s0 = axis_start.timestamp()
        s1 = axis_end.timestamp()
        span = max(1, s1 - s0)
        t = math.ceil(s0 / 3600) * 3600
        while t < s1:
            td = datetime.fromtimestamp(t, UTC).astimezone(tzl)
            ticks.append((round((t - s0) / span * 100, 3), td.strftime("%H:%M")))
            t += 3600

    parts = ['<div class="sleep-total"><span class="sleep-big">', hhmm(tot["total"]), '</span>']
    if axis_start:
        parts.append(f'<span class="sleeprange">{axis_start.strftime("%H:%M")} &rarr; {axis_end.strftime("%H:%M")}</span>')
    parts.append('</div><div class="hypno">')
    for s in segs:
        w = round(s["minutes"] * 100 / tot["total"], 3) if tot["total"] else 0
        stage = escape(s["stage"])
        parts.append(f'<div class="seg seg-{stage}" style="width:{w}%" '
                     f'title="{stage} &middot; {int(s["minutes"])} min"></div>')
    parts.append('</div>')
    if ticks:
        parts.append('<div class="hypnoaxis">')
        for pos, lbl in ticks:
            parts.append(f'<span class="tick" style="left:{pos}%">{escape(lbl)}</span>')
        parts.append('</div>')
    parts.append(
        '<div class="sleepstats">'
        f'<span><span class="dot" style="background:#dceaff"></span>Light <b>{hhmm(tot["light"])}</b></span>'
        f'<span><span class="dot" style="background:#2f6fed"></span>Deep <b>{hhmm(tot["deep"])}</b></span>'
        f'<span><span class="dot" style="background:#3f8f5f"></span>REM <b>{hhmm(tot["rem"])}</b></span>'
        f'<span><span class="dot" style="background:#c98a1f"></span>Awake <b>{hhmm(tot["awake"])}</b></span>'
        '</div>'
    )
    return Markup(''.join(parts))


def recent_value(r: dict) -> str:
    """Formatted value for the 'Recent measurements' table (raw measurements only)."""
    if r["metric"] == "blood_pressure":
        return f'{int(r["value"])}/{int(r["value2"])}'
    return f'{float(r["value"]):.1f}'.rstrip('0').rstrip('.')


def row_value(r: dict) -> str:
    """Formatted value for the unified table."""
    if r["tipo"] == "Steps":
        s = f'{int(r["v1"])} steps'
        if r["v2"] is not None:
            s += f' · {int(r["v2"])} kcal'
        if r["v3"] is not None:
            s += f' · {int(r["v3"])} m'
        return s
    if r["tipo"] == "blood_pressure":
        return f'{int(r["v1"])}/{int(r["v2"])} mmHg'
    n = f'{float(r["v1"]):.1f}'.rstrip('0').rstrip('.')
    return n + (f' {r["unit"]}' if r["unit"] else '')


def delta_badge(pct: float | None, lower_is_better: bool = False) -> Markup:
    """arrow + green/red badge: lower_is_better flips which direction counts as "good"."""
    if pct is None:
        return Markup('')
    up = pct > 0.05
    down = pct < -0.05
    arrow = '&#9650;' if up else ('&#9660;' if down else '&#9644;')
    good = down if lower_is_better else up
    bad = up if lower_is_better else down
    cls = 'good' if good else ('bad' if bad else 'flat')
    return Markup(f'<span class="delta {cls}">{arrow} {abs(pct):.1f}%</span>')
