"""
FiBand - shared configuration, read from the `.env` file (if present).

No external dependencies: a small KEY=VALUE parser.
Variables already present in the environment take precedence over the `.env` file.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_env(ROOT_DIR / ".env")

BAND_ADDRESS = os.environ.get("BAND_ADDRESS", "")
# Account name used by the "rich" bc-channel handshake (login type 0x4a).
# It's the QWatch app username (the part before the @ in the email). Configurable via .env.
BAND_ACCOUNT = os.environ.get("BAND_ACCOUNT", "ludoplus")

# SQLite database file (replaces the old MySQL/MariaDB connection).
DB_PATH = str(ROOT_DIR / os.environ.get("DB_PATH", "fiband.db"))

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")

# Local timezone used to display/group the data (and to anchor the band's
# on-device history, which is indexed in local time). Single source of truth
# for both the web dashboard and the BLE client.
FIBAND_TZ = os.environ.get("FIBAND_TZ", "Asia/Jakarta")
