
"""
FiBand - Unified collector.
Connects to the band, downloads the history (heart rate + steps) and takes
on-demand measurements (heart rate, SpO2, blood pressure, stress), saves
everything to the SQLite database.

INCREMENTAL history: by default resumes from the last data point saved in
the DB (MAX(ts)) and only downloads the missing days. Daily sync -> very
fast (today only); returning after an absence -> automatically recovers the
gap days. No marker to maintain: the source of truth is the data itself in
the DB; upserts are idempotent (re-downloading an already-saved day creates
no duplicates). Capped at MAX_DAYS beyond the device's buffer (~7 days).

Usage (CLI, standalone):
    python -m fiband.collect --mode quick                   # battery + HR + SpO2 + incremental history
    python -m fiband.collect --mode full                     # everything, including blood pressure and stress
    python -m fiband.collect --mode history                  # incremental history only (from the last data point)
    python -m fiband.collect --mode history --days 7          # override: force 7 days back
    python -m fiband.collect --mode history --from 2026-06-10T08:00   # start from a precise instant (ISO)

In the web app, `run()` is called in-process (no subprocess) by the
`/action/sync` route in `fiband/actions.py`.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from .band import Band, RT, BPResult, LOCAL_TZ
from .config import BAND_ADDRESS
from .store import Store

DEFAULT_DAYS = 7   # fallback when the DB is empty (first sync)
MAX_DAYS = 14      # cap: beyond the device's buffer (~7 days), insisting is wasted time


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr)


def resolve_days(store: Store, days_arg: int | None, from_arg: str | None) -> tuple[int, str]:
    """How many days of history to download (beyond today) and why.
    Precedence: explicit --days > explicit --from > last data point in the DB (incremental)."""
    if days_arg is not None:
        return max(0, days_arg), f"override --days={days_arg}"
    if from_arg:
        try:
            last = datetime.fromisoformat(from_arg)
        except ValueError:
            return DEFAULT_DAYS, f"invalid --from ({from_arg!r}), using default {DEFAULT_DAYS}"
        src = "--from"
    else:
        last = store.last_sample_ts()
        src = "last data point in the DB"
    if last is None:
        return DEFAULT_DAYS, f"empty DB, using default {DEFAULT_DAYS}"
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    span = (datetime.now(LOCAL_TZ).date() - last.astimezone(LOCAL_TZ).date()).days
    days = max(0, min(span, MAX_DAYS))
    note = f"{src}: last data point {last.astimezone(LOCAL_TZ):%Y-%m-%d %H:%M} -> {days} days"
    if span > MAX_DAYS:
        note += f" (capped at {MAX_DAYS}, beyond the device's buffer)"
    return days, note


async def run(address: str, mode: str, days_arg: int | None, from_arg: str | None) -> dict:
    result = {"ok": False, "battery": None, "measurements": [], "days_synced": None,
              "hr_points": 0, "step_points": 0, "stress_points": 0, "hrv_points": 0,
              "spo2_points": 0, "sleep_days": 0, "errors": []}
    store = Store()
    days, why = resolve_days(store, days_arg, from_arg)
    result["days_synced"] = days
    log(f"Incremental history: {why}")
    try:
        async with Band(address) as band:
            log("Connected to the band.")

            bat = await band.battery()
            if bat:
                store.add_measurement("battery", float(bat[0]), unit="%")
                result["battery"] = {"level": bat[0], "charging": bat[1]}
                log(f"Battery {bat[0]}% (charging={bat[1]})")

            # on-demand measurements
            if mode in ("quick", "full"):
                plan = [("heart_rate", RT.HEART_RATE, 22, "bpm"),
                        ("spo2", RT.SPO2, 22, "%")]
                if mode == "full":
                    plan += [("blood_pressure", RT.BLOOD_PRESSURE, 45, "mmHg"),
                             ("stress", RT.STRESS, 35, "score")]
                for name, kind, tmo, unit in plan:
                    log(f"Measuring {name} (max {tmo}s)...")
                    try:
                        res = await band.measure(kind, timeout=tmo)
                    except Exception as e:
                        result["errors"].append(f"{name}: {e}")
                        continue
                    if res is None:
                        log(f"  {name}: not locked")
                    elif isinstance(res, BPResult):
                        store.add_measurement("blood_pressure", float(res.systolic),
                                              value2=float(res.diastolic), unit=unit)
                        result["measurements"].append(
                            {"metric": "blood_pressure", "value": res.systolic, "value2": res.diastolic, "unit": unit})
                        log(f"  blood pressure {res.systolic}/{res.diastolic}")
                    else:
                        store.add_measurement(name, float(res), unit=unit)
                        result["measurements"].append({"metric": name, "value": res, "unit": unit})
                        log(f"  {name}: {res} {unit}")

            # history
            measured_hr = any(m["metric"] == "heart_rate" for m in result["measurements"])
            last_hr_point = None
            if mode in ("quick", "full", "history"):
                for d in range(days + 1):
                    try:
                        hr = await band.heart_rate_history(d)
                        result["hr_points"] += store.upsert_hr(hr)
                        if d == 0 and hr:
                            last_hr_point = hr[-1]
                        st = await band.steps_history(d)
                        result["step_points"] += store.upsert_steps(st)
                        stress = await band.stress_history(d)
                        result["stress_points"] += store.upsert_stress(stress)
                        hrv = await band.hrv_history(d)
                        result["hrv_points"] += store.upsert_hrv(hrv)
                        # rich bc channel: SpO2 history (sleep stages arrive in a single blob)
                        spo2 = await band.spo2_history(d)
                        result["spo2_points"] += store.upsert_spo2(spo2)
                        log(f"Day -{d}: {len(hr)} heart-rate points, {len(st)} step slots, "
                            f"{len(stress)} stress, {len(hrv)} HRV, {len(spo2)} SpO2")
                    except Exception as e:
                        result["errors"].append(f"history day -{d}: {e}")

                # Sleep: the device packs ALL stored nights into a single blob, so one
                # request is enough (see Band.sleep_nights). No per-day loop: iterating
                # the offsets would keep returning the same blob, summed as one night.
                try:
                    nights = await band.sleep_nights()
                    for night in nights:
                        store.replace_sleep(night.date.strftime("%Y-%m-%d"),
                                            [(s.stage, s.minutes) for s in night.segments],
                                            start_ts=night.start)
                    result["sleep_days"] = len(nights)
                    log("Sleep: " + (", ".join(f"{n.date:%m-%d}={n.totals()['total']}m" for n in nights)
                                      or "no nights"))
                except Exception as e:
                    result["errors"].append(f"sleep: {e}")

            # fallback: if the on-demand heart rate didn't lock, use the last one from the 24/7 log
            if not measured_hr and last_hr_point is not None:
                ts, bpm = last_hr_point
                store.add_measurement("heart_rate", float(bpm), unit="bpm", ts=ts)
                result["measurements"].append({"metric": "heart_rate", "value": bpm, "unit": "bpm", "from": "log24h"})
                log(f"Heart rate (from 24/7 log): {bpm} bpm")

            result["ok"] = True
    except Exception as e:
        result["errors"].append(str(e))
        log(f"ERROR: {e}")
    finally:
        store.close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default=BAND_ADDRESS)
    ap.add_argument("--mode", choices=["quick", "full", "history"], default="quick")
    ap.add_argument("--days", type=int, default=None,
                    help="override: force N days of history back (beyond today). "
                         "If absent, incremental sync from the last data point in the DB.")
    ap.add_argument("--from", dest="from_ts", default=None,
                    help="ISO start instant (e.g. 2026-06-10T08:00): downloads from that day "
                         "to today. Ignored if --days is given.")
    args = ap.parse_args()

    result = asyncio.run(run(args.address, args.mode, args.days, args.from_ts))
    print(json.dumps(result))  # last line = JSON


if __name__ == "__main__":
    main()
