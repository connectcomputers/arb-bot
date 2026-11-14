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

MIN_ORDER_USD = {"polymarket": 1.0, "kalshi": 0.10, "limitless": 0.10}

DATA_DIR = Path("data")

CRED_FILE = DATA_DIR / "credentials.json"
CONF_FILE = DATA_DIR / "trading_config.json"
FLAGS_FILE = DATA_DIR / "limits_flags.json"

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

from pathlib import Path as _Path
_FUNDER_FILE = _Path("data/poly_funder.txt")

def get_poly_funder() -> str:
    try:
        v = _FUNDER_FILE.read_text().strip()
        if v:
            return v
    except Exception:
        pass
    return str(((load_creds() or {}).get("polymarket") or {}).get("proxy_address") or "").strip()

def set_poly_funder(addr: str):
    _FUNDER_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FUNDER_FILE.write_text(addr.strip())


def _ensure():
    DATA_DIR.mkdir(exist_ok=True)


def _read(path: Path, default):
    if not path.exists():
        return deepcopy(default)
    try:
        return json.loads(path.read_text())
    except Exception:
        return deepcopy(default)


def _write(path: Path, obj):
    _ensure()
    path.write_text(json.dumps(obj, indent=2))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def load_creds() -> dict:
    return _read(CRED_FILE, {})


def save_creds(venue: str, creds: dict):
    allc = load_creds()
    if not isinstance(creds, dict):
        raise TypeError("creds harus berupa dict")
    allc[venue] = creds
    _write(CRED_FILE, allc)


def load_limitless_creds() -> dict:
    allc = load_creds()
    current = allc.get("limitless", {})
    base = deepcopy(DEFAULT_LIMITLESS_CREDS)
    if isinstance(current, dict):
        base.update(current)
    return base


def save_limitless_creds(creds: dict):
    if not isinstance(creds, dict):
        raise TypeError("Limitless credentials harus dict")
    current = load_limitless_creds()
    current.update(creds)
    save_creds("limitless", current)


def load_config() -> dict:
    """
    Load config trading dengan merge yang BENAR.

    Prioritas (dari rendah ke tinggi):
      1. DEFAULT_CONFIG
      2. trading_config.json (dari "Simpan Pengaturan Pair")
      3. limits_flags.json   (dari "Simpan Flag" — runtime flags)

    BUG FIX: sebelumnya memakai `_cfg` yang tidak didefinisikan,
    sehingga limits_flags.json tidak pernah ter-merge dan error
    di-swallow oleh `except Exception: pass`.
    """
    saved = _read(CONF_FILE, {})
    base = deepcopy(DEFAULT_CONFIG)

    # Merge venues satu per satu supaya venue yang tidak
    # disentuh tidak hilang.
    saved_venues = saved.get("venues", {})
    if isinstance(saved_venues, dict):
        for venue, values in saved_venues.items():
            if venue not in base["venues"]:
                base["venues"][venue] = {}
            if isinstance(values, dict):
                base["venues"][venue].update(values)

    # Merge top-level keys
    for key in ("mode", "pairs", "limits"):
        if key in saved:
            base[key] = saved[key]

    # === FIX: Merge limits_flags.json dengan benar ===
    # Gunakan `base` (bukan `_cfg` yang undefined).
    # Prioritas: limits_flags.json MENIMPA trading_config.json
    # untuk key runtime (min_pi, max_pi, requote_tol, dll).
    try:
        if FLAGS_FILE.exists():
            flags = json.loads(FLAGS_FILE.read_text())
            if isinstance(flags, dict) and flags:
                if not isinstance(base.get("limits"), dict):
                    base["limits"] = {}
                base["limits"].update(flags)
    except Exception:
        # Jangan swallow diam-diam — minimal log ke stderr
        # agar mudah debug jika file corrupt.
        import sys
        print(f"[config_store] WARN: gagal merge limits_flags.json", file=sys.stderr)

    return base


def save_config(cfg: dict):
    if not isinstance(cfg, dict):
        raise TypeError("cfg harus berupa dict")
    _write(CONF_FILE, cfg)


def set_venue_valid(venue: str, valid: bool):
    cfg = load_config()
    v = cfg["venues"].setdefault(venue, {})
    v["valid"] = bool(valid)
    v["enabled"] = bool(valid)
    save_config(cfg)

# ============================================================================================================
# # /app/config_store.py
# """
# Penyimpanan kredensial & config trading.

# credentials.json:
#     data/credentials.json

# Permission:
#     600

# Kredensial Limitless mendukung:

# wallet_mode:
#     "eoa"
#     "smartWallet"

# EOA:
#     eoa_api_key
#     wallet_pk

# Managed / Server Wallet:
#     api_key              = HMAC token ID
#     api_secret           = HMAC secret
#     delegated_profile_id = child profile ID
# """

# import json
# import os
# from pathlib import Path
# from copy import deepcopy

# MIN_ORDER_USD = {"polymarket": 1.0, "kalshi": 0.10, "limitless": 0.10}

# DATA_DIR = Path("data")

# CRED_FILE = DATA_DIR / "credentials.json"
# CONF_FILE = DATA_DIR / "trading_config.json"

# DEFAULT_CONFIG = {
#     "mode": "paper",

#     "venues": {
#         "polymarket": {
#             "valid": None,
#             "enabled": False,
#         },

#         "kalshi": {
#             "valid": None,
#             "enabled": False,
#         },

#         "limitless": {
#             "valid": None,
#             "enabled": False,
#         },
#     },

#     "pairs": [],

#     "limits": {},
# }


# DEFAULT_LIMITLESS_CREDS = {
#     "wallet_mode": "eoa",

#     # ------------------------------------------------------------
#     # Managed / Server Wallet
#     # ------------------------------------------------------------
#     "api_key": "",
#     "api_secret": "",
#     "delegated_profile_id": "",

#     # ------------------------------------------------------------
#     # Personal EOA
#     # ------------------------------------------------------------
#     "eoa_api_key": "",
#     "wallet_pk": "",
# }

# # def get_poly_funder() -> str:
# #     cfg = load_config() or {}
# #     f = str(cfg.get("poly_funder") or "").strip()
# #     if f:
# #         return f
# #     return str(((load_creds() or {}).get("polymarket") or {}).get("proxy_address") or "").strip()

# from pathlib import Path as _Path
# _FUNDER_FILE = _Path("data/poly_funder.txt")

# def get_poly_funder() -> str:
#     try:
#         v = _FUNDER_FILE.read_text().strip()
#         if v:
#             return v
#     except Exception:
#         pass
#     return str(((load_creds() or {}).get("polymarket") or {}).get("proxy_address") or "").strip()

# # def set_poly_funder(addr: str):
# #     cfg = load_config() or {}
# #     cfg["poly_funder"] = addr.strip()
# #     save_config(cfg)

# def set_poly_funder(addr: str):
#     _FUNDER_FILE.parent.mkdir(parents=True, exist_ok=True)
#     _FUNDER_FILE.write_text(addr.strip())


# def _ensure():
#     DATA_DIR.mkdir(
#         exist_ok=True
#     )


# def _read(
#     path: Path,
#     default,
# ):
#     if not path.exists():
#         return deepcopy(default)

#     try:
#         return json.loads(
#             path.read_text()
#         )

#     except Exception:
#         return deepcopy(default)


# def _write(
#     path: Path,
#     obj,
# ):
#     _ensure()

#     path.write_text(
#         json.dumps(
#             obj,
#             indent=2,
#         )
#     )

#     os.chmod(
#         path,
#         0o600,
#     )


# def load_creds() -> dict:
#     return _read(
#         CRED_FILE,
#         {},
#     )


# def save_creds(
#     venue: str,
#     creds: dict,
# ):
#     allc = load_creds()

#     if not isinstance(creds, dict):
#         raise TypeError(
#             "creds harus berupa dict"
#         )

#     allc[venue] = creds

#     _write(
#         CRED_FILE,
#         allc,
#     )


# def load_limitless_creds() -> dict:

#     allc = load_creds()

#     current = allc.get(
#         "limitless",
#         {},
#     )

#     base = deepcopy(
#         DEFAULT_LIMITLESS_CREDS
#     )

#     if isinstance(current, dict):
#         base.update(current)

#     return base


# def save_limitless_creds(
#     creds: dict,
# ):
#     if not isinstance(creds, dict):
#         raise TypeError(
#             "Limitless credentials harus dict"
#         )

#     current = load_limitless_creds()

#     current.update(creds)

#     save_creds(
#         "limitless",
#         current,
#     )


# def load_config() -> dict:

#     saved = _read(
#         CONF_FILE,
#         {},
#     )

#     base = deepcopy(
#         DEFAULT_CONFIG
#     )

#     if not isinstance(saved, dict):
#         return base

#     # Merge venue satu per satu supaya konfigurasi
#     # venue yang tidak disentuh tidak hilang.
#     saved_venues = saved.get(
#         "venues",
#         {},
#     )

#     if isinstance(saved_venues, dict):

#         for venue, values in saved_venues.items():

#             if venue not in base["venues"]:
#                 base["venues"][venue] = {}

#             if isinstance(values, dict):
#                 base["venues"][venue].update(
#                     values
#                 )

#     for key in (
#         "mode",
#         "pairs",
#         "limits",
#     ):

#         if key in saved:
#             base[key] = saved[key]

#     try:
#         import json as _jf, pathlib as _pf
#         _ov = _pf.Path("data/limits_flags.json")
#         if _ov.exists():
#             _cfg["limits"].update(_jf.loads(_ov.read_text()))
#     except Exception:
#         pass
#     return base


# def save_config(
#     cfg: dict,
# ):
#     if not isinstance(cfg, dict):
#         raise TypeError(
#             "cfg harus berupa dict"
#         )

#     _write(
#         CONF_FILE,
#         cfg,
#     )


# def set_venue_valid(
#     venue: str,
#     valid: bool,
# ):

#     cfg = load_config()

#     v = cfg["venues"].setdefault(
#         venue,
#         {},
#     )

#     v["valid"] = bool(valid)
#     v["enabled"] = bool(valid)

#     save_config(cfg)

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