# FiBand — my H59 fitness band, no app needed

![FiBand — self-hosted health data from an H59 fitness band over Bluetooth LE, no cloud](docs/og-image.png)

> **My own BLE dashboard for the H59 fitness tracker (Colmi/QWatch Pro protocol).** No cloud, no account: my health data stays on my own computer.

![Platform](https://img.shields.io/badge/platform-macOS-black)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![PHP](https://img.shields.io/badge/PHP-8%2B-777bb4)
![Database](https://img.shields.io/badge/database-MySQL%20%2F%20MariaDB-00758f)
![BLE](https://img.shields.io/badge/protocol-Bluetooth%20LE-0082fc)
![AI](https://img.shields.io/badge/AI-OpenRouter-ff4b4b)

I built this to pull the real data off my **H59** band (heart rate, SpO2, blood pressure, steps, stress, HRV) **without the QWatch Pro app**: it talks directly to the device over **Bluetooth LE** (`bleak` / CoreBluetooth), stores everything in a local **MySQL/MariaDB** database, and shows the charts in a self-hosted **PHP dashboard** — with **optional AI analysis** of my health trends via OpenRouter.

**What it does:** a cheap smartwatch / fitness band (Colmi clones, QWatch Pro / QCWatch app) → raw data under my control, nothing sent to third-party servers.

## Components
- `config.py` — reads configuration from `.env` (band address + DB).
- `band.py` — band BLE client (real-time measurements + history download).
- `store.py` — MySQL database (tables: `measurements`, `hr_samples`, `step_samples`, `stress_samples`, `hrv_samples`, `ai_report`).
- `collect.py` — collector: downloads history + on-demand measurements → MySQL. Prints a JSON summary.
- `setup.py` — one-time setup (clock + 24/7 heart-rate logging).
- `index.php` — dashboard with charts, sync buttons and **AI trend analysis** (OpenRouter).
- `start.command` — starts the dashboard.

## What I get
- **History** (fills up while wearing the band): heart rate (5 min), steps/calories/distance (15 min), stress (30 min), HRV (30 min), **SpO2 (hourly, min-max)** and **staged sleep** (light/deep/REM/awake).
- **On-demand** (instant measurement): heart rate, SpO2, blood pressure (sys/dia), stress.
- **AI analysis** (optional): send a 6-month summary — last 7 days in full detail plus a daily recap of the prior months — to a model via **OpenRouter** and get a health report on my trends (quick summary, full analysis and dietary advice), saved in the `ai_report` table.

## Requirements
- **macOS** (the BLE client uses CoreBluetooth via `bleak`).
- **Python 3.11+**.
- **PHP 8+** (e.g. via [Laravel Herd](https://herd.laravel.com/) or `brew install php`).
- **MySQL/MariaDB** listening on `127.0.0.1:3306` (Herd provides it; otherwise `brew install mariadb`).
- An **H59** band (Colmi/QC protocol, QWatch Pro app).

## Setup

> The database and tables are **created automatically** on first run — no manual SQL needed.

1. **Create the Python environment** and install dependencies:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
2. **Configure** by copying the template:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and fill in `BAND_ADDRESS` and the DB credentials (defaults are fine for a local passwordless MySQL). For the (optional) **AI analysis** add `OPENROUTER_API_KEY` (key from [openrouter.ai/keys](https://openrouter.ai/keys)) and optionally `OPENROUTER_MODEL`.
3. **Find the band address** (`BAND_ADDRESS`). Wear the band, turn off your phone's Bluetooth, then:
   ```bash
   .venv/bin/python -c "import asyncio; from bleak import BleakScanner; print('\n'.join(f'{d.address}  {d.name}' for d in asyncio.run(BleakScanner.discover())))"
   ```
   Copy the H59 device's address into `BAND_ADDRESS` in `.env`.
   *(On macOS this is a CoreBluetooth UUID, not a MAC: it is specific to your Mac.)*
4. **Initial band setup** (once — sets the clock and enables 24/7 HR logging):
   ```bash
   .venv/bin/python setup.py
   ```
   On first run macOS will ask for **Bluetooth** permission: allow it.
5. **Start the dashboard**:
   ```bash
   bash start.command          # or:  php -S 127.0.0.1:8080
   ```
   Open **http://127.0.0.1:8080**.

## Daily use
1. **Wear the band** and **turn off your phone's Bluetooth** (the band talks to one device at a time).
2. Start the dashboard (`bash start.command`) and open http://127.0.0.1:8080.
3. Press **Quick measure** (~2-3 min) / **Full measure** (~4-5 min, with blood pressure and stress) / **History only** (~2 min).
4. (Optional) Press **AI analysis** to send the last 6 months' summary to OpenRouter and get a report on the trends.

> **Incremental sync:** each sync resumes from the last data point in the database and downloads only the missing days. Daily sync → instant; if you're away for a few days while still wearing the band, a single sync on your return automatically recovers the whole buffer (the device holds ~7 days; re-downloading creates no duplicates). Manual overrides: `collect.py --days 7` or `collect.py --from 2026-06-10T08:00`.

### From your phone
While the Mac keeps the dashboard running, open `http://<Mac-IP>:8080` from your phone
(same Wi-Fi network) to view the charts. The actual band measurement always happens on the Mac.

## Layout
- `docs/` — technical notes, protocol details, snoop-log guide.

## Notes
- The band's BLE address and DB credentials live in `.env` (see `.env.example`).
- Timestamps are stored in UTC.
- SpO2 and sleep have on-device history (the "rich" BLE `bc` channel, see `band.py`): downloaded like the rest.
- **Blood pressure** has no real on-device history: the "hourly" curve shown by the official app is generated app-side (near-constant values). Here it stays on-demand only.
- **AI analysis** is optional and *opt-in*: it's the only feature that sends data off the machine (an aggregated summary, not the raw samples) and only when the button is pressed. Without `OPENROUTER_API_KEY` everything stays 100% local.
