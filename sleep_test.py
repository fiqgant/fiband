"""Dump of the raw sleep data from the band (cmd 13). Wear the band and turn
off your phone's Bluetooth, then:  .venv/bin/python sleep_test.py
Saves the raw bytes per day: needed to decode the sleep stages by comparing
them with the official app's chart."""
import asyncio

from fiband.band import Band
from fiband.config import BAND_ADDRESS


async def main() -> None:
    async with Band(BAND_ADDRESS) as band:
        days = await band.sleep_history()
        if not days:
            print("No sleep data returned.")
            return
        for d in days:
            seg = d.segments
            print(f"\n{d.date:%Y-%m-%d}  header={d.header.hex(' ')}")
            print(f"  {len(seg)} segments: {seg}")
            if seg:
                print(f"  min={min(seg)} max={max(seg)} hex={bytes(seg).hex(' ')}")


if __name__ == "__main__":
    asyncio.run(main())
