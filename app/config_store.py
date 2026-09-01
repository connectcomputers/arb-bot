# /app/config_store.py
"""
Penyimpanan kredensial & config trading.

credentials.json:
    data/credentials.json

Permission:
    600

Kredensial Limitless mendukung:

wallet_mode:
    "eoa"
    "smartWallet"

EOA:
    eoa_api_key
    wallet_pk

Managed / Server Wallet:
    api_key              = HMAC token ID
    api_secret           = HMAC secret
    delegated_profile_id = child profile ID
"""

import json
import os
from pathlib import Path
from copy import deepcopy


DATA_DIR = Path("data")

CRED_FILE = DATA_DIR / "credentials.json"
CONF_FILE = DATA_DIR / "trading_config.json"


DEFAULT_CONFIG = {
    "mode": "paper",

    "venues": {
        "polymarket": {
            "valid": None,
            "enabled": False,
        },

        "kalshi": {
            "valid": None,
            "enabled": False,
        },

        "limitless": {
            "valid": None,
            "enabled": False,
        },
    },

    "pairs": [],

    "limits": {},
}


DEFAULT_LIMITLESS_CREDS = {
    "wallet_mode": "eoa",

    # ------------------------------------------------------------
    # Managed / Server Wallet
    # ------------------------------------------------------------
    "api_key": "",
    "api_secret": "",
    "delegated_profile_id": "",

    # ------------------------------------------------------------
    # Personal EOA
    # ------------------------------------------------------------
    "eoa_api_key": "",
    "wallet_pk": "",
}


def _ensure():
    DATA_DIR.mkdir(
        exist_ok=True
    )


def _read(
    path: Path,
    default,
):
    if not path.exists():
        return deepcopy(default)

    try:
        return json.loads(
            path.read_text()
        )

    except Exception:
        return deepcopy(default)


def _write(
    path: Path,
    obj,
):
    _ensure()

    path.write_text(
        json.dumps(
            obj,
            indent=2,
        )
    )

    os.chmod(
        path,
        0o600,
    )


def load_creds() -> dict:
    return _read(
        CRED_FILE,
        {},
    )


def save_creds(
    venue: str,
    creds: dict,
):
    allc = load_creds()

    if not isinstance(creds, dict):
        raise TypeError(
            "creds harus berupa dict"
        )

    allc[venue] = creds

    _write(
        CRED_FILE,
        allc,
    )


def load_limitless_creds() -> dict:

    allc = load_creds()

    current = allc.get(
        "limitless",
        {},
    )

    base = deepcopy(
        DEFAULT_LIMITLESS_CREDS
    )

    if isinstance(current, dict):
        base.update(current)

    return base


def save_limitless_creds(
    creds: dict,
):
    if not isinstance(creds, dict):
        raise TypeError(
            "Limitless credentials harus dict"
        )

    current = load_limitless_creds()

    current.update(creds)

    save_creds(
        "limitless",
        current,
    )


def load_config() -> dict:

    saved = _read(
        CONF_FILE,
        {},
    )

    base = deepcopy(
        DEFAULT_CONFIG
    )

    if not isinstance(saved, dict):
        return base

    # Merge venue satu per satu supaya konfigurasi
    # venue yang tidak disentuh tidak hilang.
    saved_venues = saved.get(
        "venues",
        {},
    )

    if isinstance(saved_venues, dict):

        for venue, values in saved_venues.items():

            if venue not in base["venues"]:
                base["venues"][venue] = {}

            if isinstance(values, dict):
                base["venues"][venue].update(
                    values
                )

    for key in (
        "mode",
        "pairs",
        "limits",
    ):

        if key in saved:
            base[key] = saved[key]

    return base


def save_config(
    cfg: dict,
):
    if not isinstance(cfg, dict):
        raise TypeError(
            "cfg harus berupa dict"
        )

    _write(
        CONF_FILE,
        cfg,
    )


def set_venue_valid(
    venue: str,
    valid: bool,
):

    cfg = load_config()

    v = cfg["venues"].setdefault(
        venue,
        {},
    )

    v["valid"] = bool(valid)
    v["enabled"] = bool(valid)

    save_config(cfg)

# =============================================================================
# """
# Penyimpanan kredensial & config trading.
# File di data/ dengan permission 600 (owner-only).
# """
# import json
# import os
# from pathlib import Path

# DATA_DIR = Path("data")
# CRED_FILE = DATA_DIR / "credentials.json"
# CONF_FILE = DATA_DIR / "trading_config.json"

# DEFAULT_CONFIG = {
#     "mode": "paper",
#     "venues": {
#         "polymarket": {"valid": None, "enabled": False},
#         "kalshi": {"valid": None, "enabled": False},
#         "limitless": {"valid": None, "enabled": False},
#     },
#     "pairs": [],
#     "limits": {},
# }


# def _ensure():
#     DATA_DIR.mkdir(exist_ok=True)


# def _read(path: Path, default):
#     if path.exists():
#         try:
#             return json.loads(path.read_text())
#         except Exception:
#             return default
#     return default


# def _write(path: Path, obj):
#     _ensure()
#     path.write_text(json.dumps(obj, indent=2))
#     os.chmod(path, 0o600)


# def load_creds() -> dict:
#     return _read(CRED_FILE, {})


# def save_creds(venue: str, creds: dict):
#     allc = load_creds()
#     allc[venue] = creds
#     _write(CRED_FILE, allc)


# def load_config() -> dict:
#     base = json.loads(json.dumps(DEFAULT_CONFIG))
#     base.update(_read(CONF_FILE, {}))
#     return base


# def save_config(cfg: dict):
#     _write(CONF_FILE, cfg)


# def set_venue_valid(venue: str, valid: bool):
#     cfg = load_config()
#     v = cfg["venues"].setdefault(venue, {})
#     v["valid"] = bool(valid)
#     v["enabled"] = bool(valid)
#     save_config(cfg)