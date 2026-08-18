# FiBand — Technical notes (reference for the next steps)

Complete reference on the **H59** band and its BLE protocol, obtained via
reverse engineering (direct reads + HCI snoop log of the QWatch Pro app).

## Device
- Hardware model **H59** (hw `H59_V2.0`, fw `H59_2.00.14_...`), BLE name like `H59_xxxx`.
- Chip **Nordic nRF52832**. Official app: **QWatch Pro** (`com.qcwireless.qcwatch`, vendor QC Wireless / "PubuWear"). Proprietary SDK.
- **USB = charging only**, no data. All data travels over **Bluetooth Low Energy (BLE)**.
- The band connects to **one master at a time**: to use it from the PC, turn off the phone's Bluetooth.
- macOS: "cold" connect by address fails → use `BleakScanner.find_device_by_address` first.

## BLE protocol
- Data service = **Nordic UART**: `6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E`
  - RX (command writes): `6E400002-...`
  - TX (response notifications): `6E400003-...`
- **Fixed 16-byte frame**: `[cmd][payload …14 bytes…][checksum]`
  - `checksum = (sum of the first 15 bytes) & 0xFF`
- History responses = **multi-packet**: header `[cmd, 0x00, count, interval, …]`, then chunks `[cmd, idx, …values…]`. Sub-byte `0xFF` = no data.
- High bit on the command byte in the response (`cmd | 0x80`) = error/unsupported.

## Commands (map, from the snoop log)
| Function | cmd (dec) | Notes |
|---|---:|---|
| Set time | 1 | BCD payload; **the response is the capability map** (see below) |
| Battery | 3 | response: byte1 = level %, byte2 = charging |
| Heart-rate history | 21 | request = midnight timestamp (`<L`); 24 packets, 288 points/5min |
| Heart-rate log settings | 22 | `[2, enabled(1/2), interval_min]` to set; `[1]` to read |
| BP history | 20 | cmd 20 **does not respond**; but the app shows an **hourly history** (e.g. 17:00 = 129/88) → probably on the bc channel, **not yet decoded** |
| Stress history | 55 | request `[55, day]`; **decoded** (see below) — 30 min slots |
| HRV history | 57 | request `[57, day]`; **decoded** (see below) — 30 min slots, value in ms |
| Steps history | 67 | request `[day, 0x0f,0x00,0x5f,0x01]`; record per 15min slot |
| Today's summary | 72 | steps/calories/distance of the day |
| Real-time measure | 105 | start `[type, 1]`, see below |
| Stop real-time | 106 | `[type, 0, 0]` |

### Real-time (cmd 105) — decode from real bytes
Types: `1=heart rate, 2=BP, 3=SpO2, 8=stress, 10=HRV`.
Response `69 <type> <err> <b3> <b4> <b5> …`:
- **Heart rate (1)** → `byte3`
- **SpO2 (3)** → `byte3`
- **BP (2)** → `byte4 = systolic`, `byte5 = diastolic`, `byte3 = heart rate` (e.g. `117/73`, `127/79`)
- **Stress (8)** → `byte3`
- **HRV (10)** → to be refined (the value is NOT in byte3; in the probe bytes 6:7 grew like an accumulator)

The lock of optical measurements (heart rate/SpO2) is "wobbly": the sensor only locks a value with firm contact and stillness. **Retry** logic is needed to make them reliable (TODO).

### Stress (55) / HRV (57) history — decode
Same multi-packet structure as heart rate, but requested **per day index** `[cmd, day]` (0=today):
- header `[cmd, 0x00, count, interval_min, …]` — e.g. `37 00 05 1e` → 5 total packets, slots of `0x1e`=30 min.
- chunk `[cmd, idx≥1, …13 values…]` — one value per slot, `bytes[2:15]`; `0` = no measurement.
- `slot = (idx-1)*13 + position`; timestamp = midnight (UTC) + `slot*interval_min`.
- sub `0xFF` = no data for that day.
- Real example: `37 04 …2d…` → stress **45** at slot 43 (21:30); `39 04 …2c…` → HRV **44 ms** same slot.
Implemented in `band.py` (`stress_history`, `hrv_history`) → tables `stress_samples` / `hrv_samples`.

## "Rich" bc channel — historical SpO2 and sleep stages (decoded)
Besides the Nordic UART, the device exposes a **second channel ("bc")** on dedicated characteristics, with variable-length frames. This is where **historical SpO2** and **sleep stages** live (the app downloads them from here; UUID and format derived from the snoop log + byte-by-byte comparison with the app).

- Characteristics: write `de5bf72a-d711-4e47-af26-65e3012a5dc7`, notify `de5bf729-...`.
- **Frame**: `BC(0xBC) | type(1) | len(2 LE) | crc16-modbus(2 LE) | body`. Notifications can arrive **split** → they must be reassembled (see `_on_bc`).
- **Mandatory handshake** before reading: login `0x4A` with the app's account (utf-16 string, with BOM `ff fe`) + init `0x30`. The account is the QWatch username (part before the `@`), configurable via `.env` (`BAND_ACCOUNT`).
- **Debug**: `BC_DEBUG=1` dumps **all TX/RX frames** in hex on stderr (see `band.py` / `bc_test.py`). Essential for byte-by-byte comparison with the app.

**Historical SpO2 (type `0x2A`)** — request `[day]` (0=today, 1=yesterday…).
Response body: `[day] + 24 pairs (min,max)`, **one per HOUR** (00..23); pair `00 00` = hour without measurements. The app shows the hourly min-max range; we save the max. ⚠️ **These are NOT 15-min slots** (first-implementation mistake).
Verified example: hours 07→16 = `99,97,97,97,96,99,99,98,99,98` (identical to the app).

**Sleep stages (type `0x27`)** — request `[day, 0x01]`.
Body: **7-byte header** (`01 00` + start etc.), then **(stage, duration_min)** pairs. Stages: `2=light, 3=deep, 4=REM, 5=awake`. ⚠️ The order is **(stage, duration)** — not (duration, stage) — and the header is **7 bytes**, not 6 (both first-implementation mistakes).
Sleep start = minutes from midnight, `u16 LE` on `header[3:5]` (e.g. `…29 00…` → 41 → **00:41**). To be confirmed for falling asleep **before** midnight.
Verified example (night 2026-06-14): light 352, deep 90, REM 63, awake 2 → total **8h27**, start **00:41** — identical to the app.
Implemented in `band.py` (`spo2_history`, `sleep_detail`) → tables `spo2_samples` / `sleep_segments` + `sleep_sessions`.

## Real capabilities (from the cmd 1 "set time" response)
Bitmap declaring what the device can really do:
- ❌ **Body temperature: NOT supported** (marketing mentions it, the sensor isn't there).
- ✅ SpO2, BP, HRV, Stress, **Sleep** (new protocol). ❌ Blood glucose, manual heart rate.

## What has history and what doesn't
- **On-device history** (downloadable in one sync, fills up while worn): heart rate (5min), steps/calories/distance (15min), stress (30min), HRV (30min), **SpO2** (hourly, bc channel), **sleep** (stages, bc channel).
- **On-demand only** for our reads: **BP** (but the app shows an hourly history, see TODO).

## TODO / next steps
1. ✅ **Sleep and historical SpO2 decoded** on the "rich" bc channel (see dedicated section), verified byte-by-byte against the app. Still to confirm: **sleep start** for falling asleep before midnight.
2. **Decode the hourly BP history**: the app shows it (e.g. 17:00 = 129/88), cmd 20 doesn't respond → most likely another `type` of the bc channel. Capture with `BC_DEBUG=1` while the app syncs BP.
3. **Automatic retries** on real-time measurements (heart rate/SpO2/BP/stress) to increase the lock rate.
4. ✅ **Stress/HRV histories decoded and implemented** (`band.py`, 30 min slots). Still to refine: **real-time HRV** (cmd 105 type 10: value not in byte3).
5. **SpO2 min/max**: the `spo2_samples` table has a single column (we save the hourly max). Consider `spo2_min`/`spo2_max` columns to not lose the range.
6. Optional **automatic sync scheduling** (e.g. launchd) when the band is in range.
7. DB migration to a remote instance (the PC stays the BLE bridge; the cloud has no Bluetooth).

## Supporting files in this docs/ folder
- `SNOOP-LOG-GUIDE.md` — how to re-capture the HCI snoop log from Android.
- `parse_snoop.py` — btsnoop parser: extracts the band's 16-byte frames.
- `btsnoop_hci.log` — raw capture of QWatch Pro traffic (useful for decoding sleep).
- `Hack the watch.md` / `.html` — article about the project.