"""
Live-Fee Fetch — Tahap 10-A.
Mengambil fee live dari API bursa dengan cache + fallback.
"""
import json
import time
from pathlib import Path
from typing import Optional
from decimal import Decimal

import httpx

# Cache sederhana (in-memory + file)
CACHE_FILE = Path("data/fee_cache.json")
CACHE_TTL_SECONDS = 1800  # 30 menit

_cache = {}


def _load_cache():
    """Load cache dari file."""
    global _cache
    if CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            _cache = {}


def _save_cache():
    """Simpan cache ke file."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(_cache, indent=2, default=str))


def _get_cached(key: str) -> Optional[dict]:
    """Ambil dari cache jika belum expired."""
    if not _cache:
        _load_cache()
    
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry["ts"] < CACHE_TTL_SECONDS:
            return entry["data"]
    return None


def _set_cached(key: str, data: dict):
    """Simpan ke cache."""
    _cache[key] = {"ts": time.time(), "data": data}
    _save_cache()


# ============ KALSHI ============
async def fetch_kalshi_fee_live(ticker: str) -> dict:
    """
    Fetch fee Kalshi per ticker.
    Return: {"fee_rate": Decimal, "is_non_standard": bool}
    """
    cache_key = f"kalshi:{ticker}"
    cached = _get_cached(cache_key)
    if cached:
        return {
            "fee_rate": Decimal(str(cached["fee_rate"])),
            "is_non_standard": cached["is_non_standard"],
        }
    
    url = f"https://external-api.kalshi.com/trade-api/v2/markets/{ticker}/fee"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            
            data = resp.json()
            fee_bps = data.get("taker_fee_bps", 7)  # default 7 bps
            fee_rate = Decimal(str(fee_bps)) / Decimal("10000")
            is_non_standard = data.get("is_non_standard", False)
            
            result = {
                "fee_rate": fee_rate,
                "is_non_standard": is_non_standard,
            }
            _set_cached(cache_key, {"fee_rate": str(fee_rate), "is_non_standard": is_non_standard})
            return result
    except Exception as e:
        # Fallback: gunakan fee default 0.07 (7 bps)
        print(f"⚠ Kalshi fee fetch gagal untuk {ticker}: {e}. Fallback ke default 0.07.")
        return {"fee_rate": Decimal("0.07"), "is_non_standard": False}


# ============ POLYMARKET ============
async def fetch_polymarket_fee_live(condition_id: str) -> dict:
    """
    Fetch fee Polymarket per condition.
    Return: {"fee_rate": Decimal}
    """
    cache_key = f"polymarket:{condition_id}"
    cached = _get_cached(cache_key)
    if cached:
        return {"fee_rate": Decimal(str(cached["fee_rate"]))}
    
    url = f"https://clob.polymarket.com/markets/{condition_id}/fee-rate"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            
            data = resp.json()
            fee_rate = Decimal(str(data.get("fee_rate", 0.05)))
            
            result = {"fee_rate": fee_rate}
            _set_cached(cache_key, {"fee_rate": str(fee_rate)})
            return result
    except Exception as e:
        # Fallback: gunakan fee default 0.05 (5%)
        print(f"⚠ Polymarket fee fetch gagal untuk {condition_id}: {e}. Fallback ke default 0.05.")
        return {"fee_rate": Decimal("0.05")}


# ============ LIMITLESS ============
async def fetch_limitless_fee_schedule_live() -> dict:
    """
    Fetch fee schedule Limitless.
    Return: {"buy": [[price, rate], ...], "sell": [[price, rate], ...], "amm": Decimal}
    """
    cache_key = "limitless:schedule"
    cached = _get_cached(cache_key)
    if cached:
        return {
            "buy": cached["buy"],
            "sell": cached["sell"],
            "amm": Decimal(str(cached["amm"])),
        }
    
    url = "https://api.limitless.com/v1/fee-schedule"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            
            data = resp.json()
            result = {
                "buy": data.get("buy", []),
                "sell": data.get("sell", []),
                "amm": Decimal(str(data.get("amm", 0.004))),
            }
            _set_cached(cache_key, {
                "buy": result["buy"],
                "sell": result["sell"],
                "amm": str(result["amm"]),
            })
            return result
    except Exception as e:
        # Fallback: gunakan schedule default dari blueprint
        print(f"⚠ Limitless fee fetch gagal: {e}. Fallback ke schedule default.")
        return {
            "buy": [
                [Decimal("0.50"), Decimal("0.03")],
                [Decimal("0.55"), Decimal("0.0252")],
                [Decimal("0.60"), Decimal("0.0213")],
            ],
            "sell": [
                [Decimal("0.01"), Decimal("0.0042")],
                [Decimal("0.05"), Decimal("0.0060")],
                [Decimal("0.10"), Decimal("0.0078")],
            ],
            "amm": Decimal("0.004"),
        }

def clear_cache():
    """Kosongkan cache in-memory + file (untuk testing & maintenance)."""
    global _cache
    _cache = {}
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
    except Exception:
        pass    