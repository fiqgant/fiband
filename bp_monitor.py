
"""
FiBand - Blood pressure (and heart rate/SpO2) monitor at intervals.

The band does NOT keep a downloadable blood pressure history over the 16-byte
protocol: the official app builds the curve by taking a measurement every hour
and saving it. This script does the same on our side: every N minutes it
connects, measures blood pressure (and, for free, heart rate + SpO2 since it's
already connected), saves to MySQL and disconnects — so the phone can use the
band the rest of the time.

Usage (wear the band near the Mac, phone Bluetooth OFF):
    .venv/bin/python bp_monitor.py --once        # a single measurement (test)
    .venv/bin/python bp_monitor.py               # every 60 min, until stopped (Ctrl-C)
    .venv/bin/python bp_monitor.py --interval 30 # every 30 min
"""
import argparse
import asyncio
import sys
from datetime import datetime

from band import Band, RT, BPResult
from config import BAND_ADDRESS
from store import Store


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


async def one_reading(store: Store) -> bool:
    """A single reading: blood pressure + heart rate + SpO2. True if blood pressure locked."""
    try:
        async with Band(BAND_ADDRESS) as band:
            bat = await band.battery()
            if bat:
                store.add_measurement("battery", float(bat[0]), unit="%")

            res = await band.measure(RT.BLOOD_PRESSURE, timeout=60)
            if not isinstance(res, BPResult):
                log("blood pressure did not lock (band worn snugly and still?)")
                return False
            store.add_measurement("blood_pressure", float(res.systolic),
                                  value2=float(res.diastolic), unit="mmHg")

            # already connected: also grab heart rate and SpO2 for tonight's comparison
            hr = await band.measure(RT.HEART_RATE, timeout=25)
            if hr:
                store.add_measurement("heart_rate", float(hr), unit="bpm")
            spo2 = await band.measure(RT.SPO2, timeout=25)
            if spo2:
                store.add_measurement("spo2", float(spo2), unit="%")

            log(f"OK  blood pressure {res.systolic}/{res.diastolic} mmHg"
                + (f", heart rate {hr} bpm" if hr else "")
                + (f", SpO2 {spo2}%" if spo2 else ""))
            return True
    except Exception as e:
        log(f"error: {e}")
        return False


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60, help="minutes between measurements")
    ap.add_argument("--once", action="store_true", help="a single measurement, then exit")
    args = ap.parse_args()

    if not BAND_ADDRESS:
        log("BAND_ADDRESS not configured in .env"); sys.exit(1)

    store = Store()
    n = 0
    try:
        while True:
            n += 1
            log(f"--- reading #{n} ---")
            await one_reading(store)
            if args.once:
                break
            log(f"next reading in {args.interval} min (Ctrl-C to stop)")
            await asyncio.sleep(args.interval * 60)
    finally:
        store.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("stopped.")
