"""
FiBand - BLE client for the H59 band (Colmi/QC protocol, Nordic UART).

Real-time measurements (cmd 105, decoded from real device bytes):
  - Heart rate (1) -> byte[3]
  - SpO2 (3)       -> byte[3]
  - Blood pressure (2) -> byte[4]=systolic, byte[5]=diastolic, byte[3]=heart rate
  - Stress (8)     -> byte[3]
Downloadable history (fills up while wearing the band):
  - Heart rate (cmd 21): daily curve at 5-minute steps (288 points)
  - Steps/calories/distance (cmd 67): at 15-minute steps
Battery: cmd 3. Setup: set_time (cmd 1), 24/7 heart-rate logging (cmd 22).
"""
from __future__ import annotations

import asyncio
import os
import statistics
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from bleak import BleakClient, BleakScanner

# The band keeps its clock in LOCAL time (not UTC): we anchor the history to
# this timezone and let store.py convert to UTC when saving to the DB.
LOCAL_TZ = ZoneInfo("Asia/Jakarta")

RX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# "Rich" bc channel: detailed history (slotted SpO2, sleep stages) on dedicated
# characteristics, variable-length frame protocol: bc | type(1) | len(2 LE) | crc16-modbus(2 LE) | body
# (UUID and format derived from the official app's btsnoop log).
BC_WRITE = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
BC_NOTIFY = "de5bf729-d711-4e47-af26-65e3012a5dc7"
BC_MAGIC = 0xBC

BC_LOGIN = 0x4A     # login with the app's account
BC_INIT = 0x30      # init/handshake
BC_SLEEP = 0x27     # sleep stages
BC_SPO2 = 0x2A      # historical slotted SpO2

SLEEP_STAGES = {2: "light", 3: "deep", 4: "rem", 5: "awake"}

# Dumps raw bc-channel frames (TX/RX) to stderr for byte-by-byte comparison
# with the official app. Off by default; enable with BC_DEBUG=1 (see bc_test.py).
BC_DEBUG = os.environ.get("BC_DEBUG", "") not in ("", "0", "false", "False")


def _bclog(tag: str, data: bytes) -> None:
    if BC_DEBUG:
        print(f"[{datetime.now():%H:%M:%S.%f} bc {tag}] {bytes(data).hex(' ')}", file=sys.stderr)

CMD_SET_TIME = 1
CMD_BATTERY = 3
CMD_HR_HISTORY = 21
CMD_HR_LOG = 22
CMD_STRESS_HISTORY = 55
CMD_HRV_HISTORY = 57
CMD_STEPS = 67
CMD_SLEEP_HISTORY = 13
CMD_REALTIME = 105
CMD_REALTIME_STOP = 106


class RT:
    HEART_RATE = 1
    BLOOD_PRESSURE = 2
    SPO2 = 3
    STRESS = 8
    HRV = 10


def checksum(p: bytearray) -> int:
    return sum(p) & 255


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc


def bc_frame(typ: int, body: bytes = b"") -> bytes:
    """Builds a rich-channel frame: bc | type | len | crc16-modbus | body."""
    return (bytes([BC_MAGIC, typ]) + struct.pack("<H", len(body))
            + struct.pack("<H", crc16_modbus(body)) + body)


def make_packet(cmd: int, sub: bytes = b"") -> bytearray:
    p = bytearray(16)
    p[0] = cmd
    for i, b in enumerate(sub):
        p[i + 1] = b
    p[-1] = checksum(p)
    return p


def byte_to_bcd(b: int) -> int:
    return ((b // 10) << 4) | (b % 10)


def bcd_to_dec(b: int) -> int:
    return ((b >> 4) & 15) * 10 + (b & 15)


def midnight_ts(day: int = 0) -> int:
    now = datetime.now(LOCAL_TZ)
    mid = datetime(now.year, now.month, now.day, tzinfo=LOCAL_TZ)
    return int(mid.timestamp()) - day * 86400


@dataclass
class BPResult:
    systolic: int
    diastolic: int
    heart_rate: int | None = None


@dataclass
class SleepDay:
    date: datetime          # midnight of the day (local time)
    header: bytes            # raw frame header (for future decoding)
    segments: list[int]      # raw sleep segment bytes (semantics to be confirmed)


@dataclass
class SleepSegment:
    stage: str              # light | deep | rem | awake
    minutes: int


@dataclass
class SleepDetail:
    date: datetime              # night's date (midnight, local time)
    header: bytes                # 6-byte raw header (start time etc.)
    segments: list[SleepSegment]
    start: datetime | None = None   # sleep start instant (estimated from the header)

    def totals(self) -> dict[str, int]:
        out = {s: 0 for s in ("light", "deep", "rem", "awake")}
        for seg in self.segments:
            out[seg.stage] = out.get(seg.stage, 0) + seg.minutes
        out["total"] = sum(s.minutes for s in self.segments)
        return out


class Band:
    def __init__(self, address: str):
        self.address = address
        self.client: BleakClient | None = None
        self._rt_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._hist: list[bytes] = []
        self._collecting = False
        self._other: dict[int, bytes] = {}
        self._bc_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._bc_buf = bytearray()
        self._bc_ready = False

    async def __aenter__(self) -> "Band":
        device = await BleakScanner.find_device_by_address(self.address, timeout=15)
        if device is None:
            raise RuntimeError("Band not found (worn? phone Bluetooth off?)")
        self.client = BleakClient(device, timeout=20)
        await self.client.connect()
        await self.client.start_notify(TX, self._on_tx)
        try:
            await self.client.start_notify(BC_NOTIFY, self._on_bc)
            self._bc_ready = True
        except Exception:
            self._bc_ready = False  # firmware without the rich channel: bc history unavailable
        return self

    async def __aexit__(self, *exc) -> None:
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass

    def _on_tx(self, _, data: bytearray) -> None:
        b = bytes(data)
        if b[0] == CMD_REALTIME:
            self._rt_q.put_nowait(b)
        else:
            self._other[b[0]] = b
            if self._collecting:
                self._hist.append(b)

    async def _send(self, pkt: bytearray) -> None:
        assert self.client is not None
        await self.client.write_gatt_char(RX, pkt, response=False)

    async def _request(self, cmd: int, sub: bytes = b"", wait: float = 2.8) -> list[bytes]:
        """Sends a command and collects all response packets within `wait`."""
        self._hist = []
        self._collecting = True
        await self._send(make_packet(cmd, sub))
        await asyncio.sleep(wait)
        self._collecting = False
        return [p for p in self._hist if p[0] == cmd]

    # ---------- setup ----------
    async def set_time(self, dt: datetime | None = None) -> dict:
        if dt is None:
            dt = datetime.now(LOCAL_TZ)
        dt = dt.astimezone(LOCAL_TZ)
        data = bytes([
            byte_to_bcd(dt.year % 2000), byte_to_bcd(dt.month), byte_to_bcd(dt.day),
            byte_to_bcd(dt.hour), byte_to_bcd(dt.minute), byte_to_bcd(dt.second), 1,
        ])
        self._other.pop(CMD_SET_TIME, None)
        await self._send(make_packet(CMD_SET_TIME, data))
        for _ in range(30):
            if CMD_SET_TIME in self._other:
                break
            await asyncio.sleep(0.1)
        resp = self._other.get(CMD_SET_TIME)
        if not resp:
            return {}
        b = resp[1:]
        return {
            "temperature": b[0] == 1, "spo2": bool(b[3] & 2), "blood_pressure": bool(b[3] & 4),
            "stress": bool(b[13] & 16), "hrv": bool(b[13] & 32), "sleep": b[8] == 1,
        }

    async def set_hr_logging(self, enabled: bool, interval_min: int = 5) -> None:
        await self._send(make_packet(CMD_HR_LOG, bytes([2, 1 if enabled else 2, interval_min])))
        await asyncio.sleep(0.4)

    # ---------- direct reads ----------
    async def battery(self) -> tuple[int, bool] | None:
        self._other.pop(CMD_BATTERY, None)
        await self._send(make_packet(CMD_BATTERY))
        for _ in range(30):
            if CMD_BATTERY in self._other:
                p = self._other[CMD_BATTERY]
                return p[1], bool(p[2])
            await asyncio.sleep(0.1)
        return None

    # ---------- real-time (on-demand) measurements ----------
    async def measure(self, rtype: int, timeout: float = 30.0, want: int = 6):
        while not self._rt_q.empty():
            self._rt_q.get_nowait()
        await self._send(make_packet(CMD_REALTIME, bytes([rtype, 1])))
        primary: list[int] = []
        bp: list[tuple[int, int, int]] = []
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    p = await asyncio.wait_for(self._rt_q.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                if len(p) < 7 or p[1] != rtype or p[2] != 0:
                    if len(p) >= 3 and p[2] != 0:
                        break
                    continue
                if rtype == RT.BLOOD_PRESSURE:
                    if p[4] and p[5]:
                        bp.append((p[4], p[5], p[3]))
                        if len(bp) >= 3:
                            break
                elif p[3]:
                    primary.append(p[3])
                    if len(primary) >= want:
                        break
        finally:
            await self._send(make_packet(CMD_REALTIME_STOP, bytes([rtype, 0, 0])))
        if rtype == RT.BLOOD_PRESSURE:
            if not bp:
                return None
            return BPResult(int(statistics.median(s[0] for s in bp)),
                            int(statistics.median(s[1] for s in bp)),
                            int(statistics.median(s[2] for s in bp)) or None)
        return int(statistics.median(primary)) if primary else None

    # ---------- history ----------
    async def heart_rate_history(self, day: int = 0) -> list[tuple[datetime, int]]:
        """Heart-rate curve for the day (0=today) at 5-minute steps."""
        ts = midnight_ts(day)
        # The band indexes its history by LOCAL-time midnight encoded as if it
        # were UTC (a "naive" clock): the timezone offset must be added to the
        # UTC timestamp, otherwise the request falls into the previous day and
        # the device replies "no data".
        base = datetime.fromtimestamp(ts, LOCAL_TZ)
        band_ts = ts + int(base.utcoffset().total_seconds())
        packets = await self._request(CMD_HR_HISTORY, struct.pack("<L", band_ts), wait=3.5)
        size = 0
        raw: list[int] = []
        index = 0
        for p in packets:
            sub = p[1]
            if sub == 0xff:
                return []
            if sub == 0:
                size = p[2]
                raw = [0] * (size * 13)
            elif sub == 1:
                raw[0:9] = list(p[6:15])
                index = 9
            else:
                raw[index:index + 13] = list(p[2:15])
                index += 13
        out = []
        for i, hr in enumerate(raw[:288]):
            if hr:
                out.append((base + timedelta(minutes=5 * i), hr))
        return out

    async def _slot_history(self, cmd: int, day: int) -> list[tuple[datetime, int]]:
        """Slotted history (stress cmd 55, HRV cmd 57): 1 value per slot, requested per day.
        Multi-packet response: header [cmd, 0, count, interval_min, ...],
        chunk [cmd, idx>=1, ...13 values...]. Value 0 = no measurement in that slot.
        """
        packets = await self._request(cmd, bytes([day]), wait=3.0)
        interval = 30
        values: dict[int, int] = {}
        for p in packets:
            sub = p[1]
            if sub == 0xff:
                return []
            if sub == 0:
                interval = p[3] or 30
            else:
                for i, v in enumerate(p[2:15]):
                    if v:
                        values[(sub - 1) * 13 + i] = v
        base = datetime.fromtimestamp(midnight_ts(day), LOCAL_TZ)
        return [(base + timedelta(minutes=interval * slot), v) for slot, v in sorted(values.items())]

    async def stress_history(self, day: int = 0) -> list[tuple[datetime, int]]:
        """Stress curve for the day (0=today), 1 value per 30-minute slot."""
        return await self._slot_history(CMD_STRESS_HISTORY, day)

    async def hrv_history(self, day: int = 0) -> list[tuple[datetime, int]]:
        """HRV curve (ms) for the day (0=today), 1 value per 30-minute slot."""
        return await self._slot_history(CMD_HRV_HISTORY, day)

    async def sleep_history(self) -> list["SleepDay"]:
        """Sleep history (cmd 13). The device replies with multiple days at once:
        for each day a header frame [13, 0x00, YY, MM, DD, 0x3c, ...] followed by one
        or more data frames [13, idx>=1, ...segment bytes...]; 0xff closes the list.

        NOTE: the semantics of the segment bytes are NOT yet confirmed (observed
        values ~0x35-0x47). For now we return the raw bytes per day: they need to be
        decoded with certainty by comparing a full night with the official app's
        sleep chart (same method used for HR/steps).
        """
        packets = await self._request(CMD_SLEEP_HISTORY, wait=3.0)
        days: list[SleepDay] = []
        cur: SleepDay | None = None
        for p in packets:
            sub = p[1]
            if sub == 0xff:
                break
            if sub == 0x00:
                try:
                    d = datetime(2000 + p[2], p[3], p[4], tzinfo=LOCAL_TZ)
                except ValueError:
                    cur = None
                    continue
                cur = SleepDay(date=d, header=bytes(p), segments=[])
                days.append(cur)
            elif cur is not None:
                cur.segments.extend(p[2:15])
        for d in days:  # strip trailing zero-padding
            while d.segments and d.segments[-1] == 0:
                d.segments.pop()
        return days

    # ---------- rich bc channel: historical SpO2 + sleep stages ----------
    def _on_bc(self, _, data: bytearray) -> None:
        """Reassembles bc frames (they can arrive split across multiple notifications)."""
        _bclog("RX raw", data)
        self._bc_buf += bytes(data)
        while True:
            i = self._bc_buf.find(BC_MAGIC)
            if i < 0:
                self._bc_buf.clear(); return
            if i:
                del self._bc_buf[:i]
            if len(self._bc_buf) < 6:
                return
            ln = struct.unpack_from("<H", self._bc_buf, 2)[0]
            total = 6 + ln
            if len(self._bc_buf) < total:
                return
            frame = bytes(self._bc_buf[:total])
            del self._bc_buf[:total]
            _bclog(f"RX frame type=0x{frame[1]:02x}", frame)
            self._bc_q.put_nowait(frame)

    def _bc_drain(self) -> None:
        while not self._bc_q.empty():
            try:
                self._bc_q.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _bc_send(self, typ: int, body: bytes = b"") -> None:
        assert self.client is not None
        frame = bc_frame(typ, body)
        _bclog(f"TX type=0x{typ:02x}", frame)
        await self.client.write_gatt_char(BC_WRITE, frame, response=False)

    async def _bc_request(self, typ: int, body: bytes, wait: float = 4.0) -> bytes | None:
        """Sends a bc request and returns the body of the longest response of the same type."""
        self._bc_drain()
        await self._bc_send(typ, body)
        best = b""
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                frame = await asyncio.wait_for(self._bc_q.get(), timeout=wait)
            except asyncio.TimeoutError:
                break
            if frame[1] != typ:
                continue
            ln = struct.unpack_from("<H", frame, 2)[0]
            fb = frame[6:6 + ln]
            if len(fb) > len(best):
                best = fb
            if len(fb) > 3:   # data response (not a plain ack)
                break
        return best or None

    async def _bc_login(self) -> bool:
        """Rich-channel handshake: login with the account + init. True if it looks ok."""
        from config import BAND_ACCOUNT
        if not self._bc_ready:
            return False
        body = b"\x01\x01\x00" + BAND_ACCOUNT.encode("utf-16")  # 'utf-16' includes the ff fe BOM
        await self._bc_send(BC_LOGIN, body)
        await asyncio.sleep(0.4)
        await self._bc_send(BC_INIT)
        await asyncio.sleep(0.4)
        self._bc_drain()
        return True

    async def spo2_history(self, day: int = 0) -> list[tuple[datetime, int]]:
        """Historical SpO2 curve for the day (0=today, 1=yesterday...): 1 value per HOUR.

        Body: [day] + 24 (min, max) pairs, one per hour (00..23); pair 00 00 = hour
        with no measurements. The app shows the min-max range per hour; here we save
        the maximum. (Verified byte-by-byte against the official app: hours 07->16 =
        99,97,97,97,96,99,99,98,99,98.)
        """
        if not await self._bc_login():
            return []
        body = await self._bc_request(BC_SPO2, bytes([(-day) & 0xFF]))
        if not body or len(body) < 3:
            return []
        pairs = body[1:]  # skip the day byte
        base = datetime.fromtimestamp(midnight_ts(day), LOCAL_TZ)
        out = []
        for h in range(min(24, len(pairs) // 2)):
            lo, hi = pairs[2 * h], pairs[2 * h + 1]
            if hi:  # 00 = hour with no measurements
                out.append((base + timedelta(hours=h), hi))
        return out

    def _parse_sleep_blob(self, body: bytes) -> list["SleepDetail"]:
        """Decodes the sleep blob. Verified byte-by-byte against the official app.

        The device does NOT return one night per request: it packs ALL stored
        nights into a single blob (for day>=1 it ignores the parameter and always
        returns everything; for day=0 it returns only the most recent night, but in
        the same format). Structure:

            body[0] = N (number of nights)
            then N records:  [idx][?][start_u16 LE][end_u16 LE]  +  (stage, duration) pairs
            - idx counts backwards: 0 = most recent night -> today, k -> today-k
            - start/end = minutes from midnight; night duration = (end - start) mod 1440
            - the (stage 2=light/3=deep/4=REM/5=awake, duration_min) pairs sum up to
              exactly the duration: that's what delimits one record from the next.
        """
        out: list[SleepDetail] = []
        if not body or len(body) < 8:
            return out
        n = body[0]
        i = 1
        for _ in range(n):
            if i + 6 > len(body):
                break
            idx = body[i]
            start_min = body[i + 2] | body[i + 3] << 8
            end_min = body[i + 4] | body[i + 5] << 8
            dur = (end_min - start_min) % 1440
            i += 6
            segs: list[SleepSegment] = []
            acc = 0
            while i + 2 <= len(body) and acc < dur:
                stage, du = body[i], body[i + 1]
                if stage not in SLEEP_STAGES:
                    break
                if du:
                    segs.append(SleepSegment(SLEEP_STAGES[stage], du))
                acc += du
                i += 2
            if not segs:
                continue
            base = datetime.fromtimestamp(midnight_ts(idx), LOCAL_TZ)
            out.append(SleepDetail(date=base, header=b"", segments=segs,
                                   start=base + timedelta(minutes=start_min)))
        return out

    async def sleep_nights(self) -> list["SleepDetail"]:
        """All nights stored on the band, from a SINGLE bc 0x27 request
        (the device packs them all into one blob; see _parse_sleep_blob)."""
        if not await self._bc_login():
            return []
        body = await self._bc_request(BC_SLEEP, bytes([0xff, 0x01]))  # day>=1 -> full blob
        return self._parse_sleep_blob(body or b"")

    async def sleep_detail(self, day: int = 0) -> "SleepDetail | None":
        """Single night at offset `day` (0=today, 1=yesterday...). Uses the blob parser."""
        want = datetime.fromtimestamp(midnight_ts(day), LOCAL_TZ).date()
        return next((s for s in await self.sleep_nights() if s.date.date() == want), None)

    async def steps_history(self, day: int = 0) -> list[tuple[datetime, int, int, int]]:
        """Returns (timestamp, steps, calories, distance_m) per 15-minute slot."""
        packets = await self._request(CMD_STEPS, bytes([day, 0x0f, 0x00, 0x5f, 0x01]), wait=3.0)
        out = []
        for p in packets:
            if p[1] in (0xff, 0xf0):
                continue
            year = bcd_to_dec(p[1]) + 2000
            month = bcd_to_dec(p[2])
            d = bcd_to_dec(p[3])
            time_index = p[4]
            cal = p[7] | (p[8] << 8)
            steps = p[9] | (p[10] << 8)
            dist = p[11] | (p[12] << 8)
            try:
                t = datetime(year, month, d, time_index // 4, (time_index % 4) * 15, tzinfo=LOCAL_TZ)
            except ValueError:
                continue
            out.append((t, steps, cal, dist))
        return out
