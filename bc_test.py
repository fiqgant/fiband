"""
Test for the "rich" bc channel: downloads historical SpO2 + sleep stages from the
band and prints them (does NOT save to the DB). Used to verify the handshake and
parsing live.

Wear the band near the Mac, phone Bluetooth OFF, then:
    .venv/bin/python bc_test.py            # today
    .venv/bin/python bc_test.py --day 1    # yesterday

For byte-by-byte comparison with the official app, enable the raw frame dump
(bc-channel TX/RX) to stderr and save it to a file:
    BC_DEBUG=1 .venv/bin/python bc_test.py --day 1 2> bc_raw.log
"""
import argparse
import asyncio

from band import Band
from config import BAND_ADDRESS, BAND_ACCOUNT


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", type=int, default=0, help="0=today, 1=yesterday, ...")
    args = ap.parse_args()

    async with Band(BAND_ADDRESS) as band:
        if not band._bc_ready:
            print("bc channel not available on this band/firmware.")
            return
        print(f"Account handshake: {BAND_ACCOUNT}")

        spo2 = await band.spo2_history(args.day)
        print(f"\n### Historical SpO2 (day -{args.day}): {len(spo2)} points")
        for ts, v in spo2[:8]:
            print(f"  {ts:%H:%M}  {v}%")
        if len(spo2) > 8:
            print(f"  ... (+{len(spo2)-8})")

        sleep = await band.sleep_detail(args.day)
        if not sleep:
            print(f"\n### Sleep (day -{args.day}): no data")
            return
        t = sleep.totals()
        print(f"\n### Sleep (day -{args.day}): {len(sleep.segments)} segments, "
              f"total {t['total']//60}h{t['total']%60:02d}")
        print(f"  light {t['light']}m · deep {t['deep']}m · "
              f"REM {t['rem']}m · awake {t['awake']}m")
        print(f"  raw header: {sleep.header.hex(' ')}")


if __name__ == "__main__":
    asyncio.run(main())
