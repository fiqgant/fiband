
"""
FiBand - One-time band setup:
  - sets the internal clock (correct timestamps for the history)
  - enables automatic 24/7 heart-rate logging (default every 5 min)
  - shows the device's real capabilities

Usage: python setup.py [--interval 5]
WEAR the band, phone Bluetooth OFF.
"""
import argparse
import asyncio

from fiband.band import Band
from fiband.config import BAND_ADDRESS


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default=BAND_ADDRESS)
    ap.add_argument("--interval", type=int, default=5)
    args = ap.parse_args()

    async with Band(args.address) as band:
        print("Connected.")
        caps = await band.set_time()
        print("Clock set. Capabilities:", caps)
        await band.set_hr_logging(True, args.interval)
        print(f"24/7 heart-rate logging enabled (every {args.interval} min).")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
