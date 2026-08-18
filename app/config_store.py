"""
Penyimpanan kredensial & config trading.
File di data/ dengan permission 600 (owner-only).
"""
import json
import os
from pathlib import Path

DATA_DIR = Path("data")
CRED_FILE = DATA_DIR / "credentials.json"
CONF_FILE = DATA_DIR / "trading_config.json"

DEFAULT_CONFIG = {
    "mode": "paper",
    "venues": {
        "polymarket": {"valid": None, "enabled": False},
        "kalshi": {"valid": None, "enabled": False},
        "limitless": {"valid": None, "enabled": False},
    },
    "pairs": [],
    "limits": {},
}


def _ensure():
    DATA_DIR.mkdir(exist_ok=True)


def _read(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def _write(path: Path, obj):
    _ensure()
    path.write_text(json.dumps(obj, indent=2))
    os.chmod(path, 0o600)


def load_creds() -> dict:
    return _read(CRED_FILE, {})


def save_creds(venue: str, creds: dict):
    allc = load_creds()
    allc[venue] = creds
    _write(CRED_FILE, allc)


def load_config() -> dict:
    base = json.loads(json.dumps(DEFAULT_CONFIG))
    base.update(_read(CONF_FILE, {}))
    return base


def save_config(cfg: dict):
    _write(CONF_FILE, cfg)


def set_venue_valid(venue: str, valid: bool):
    cfg = load_config()
    v = cfg["venues"].setdefault(venue, {})
    v["valid"] = bool(valid)
    v["enabled"] = bool(valid)
    save_config(cfg)