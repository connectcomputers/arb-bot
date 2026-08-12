"""
Settlement & Rekonsiliasi — Tahap 9.
Status:
- MATCH   : 1 kaki menang & realized >= expected (proyeksi konservatif terpenuhi)
- MISMATCH: 1 kaki menang & realized < expected (anomali fee/slippage)
- SETTLEMENT_CONFLICT: hasil BUKAN 1-1 → indikasi false-friend → ALERT
- PENDING : belum semua leg settle
"""
import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
KALSHI_MARKET_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "application/json",
}
LEDGER_FILE = Path("data") / "ledger.json"


# ---------- Fetch resolusi ----------
def _parse_poly_resolution(m: dict) -> Optional[str]:
    if not (m.get("closed") or m.get("resolved")):
        return None
    outcomes, prices = m.get("outcomes"), m.get("outcomePrices")
    if not outcomes or not prices:
        return None
    try:
        outs = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        prs = json.loads(prices) if isinstance(prices, str) else prices
    except Exception:
        return None
    for o, p in zip(outs, prs):
        try:
            if Decimal(str(p)) >= Decimal("0.999"):
                return str(o).strip().upper()
        except Exception:
            continue
    return None


async def fetch_poly_resolution(client: httpx.AsyncClient, condition_id: str) -> Optional[str]:
    for param in ("condition_id", "condition_ids"):
        try:
            resp = await client.get(GAMMA_URL, params={param: condition_id},
                                    headers=HEADERS, timeout=15.0)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    res = _parse_poly_resolution(data[0])
                    if res:
                        return res
        except Exception:
            continue
    return None


async def fetch_kalshi_resolution(client: httpx.AsyncClient, ticker: str) -> Optional[str]:
    try:
        resp = await client.get(f"{KALSHI_MARKET_URL}/{ticker}",
                                headers=HEADERS, timeout=15.0)
        if resp.status_code != 200:
            return None
        m = resp.json().get("market", {})
        if str(m.get("status", "")).lower() not in ("settled", "closed"):
            return None
        result = str(m.get("result", "")).strip().lower()
        return result.upper() if result in ("yes", "no") else None
    except Exception:
        return None


# ---------- Hitung settlement (murni, testable) ----------
def compute_settlement(record: dict,
                       resolutions: Dict[Tuple[str, str], Optional[str]]) -> dict:
    legs, pending, wins = [], False, 0
    total_cost = Decimal("0")
    total_payout = Decimal("0")

    for o in record.get("orders", []):
        res = resolutions.get((o.get("venue"), o.get("market_id")))
        if res is None:
            pending = True
            legs.append({**o, "won": None, "payout": None})
            continue

        size = int(o.get("size", 0))
        price = Decimal(str(o.get("price", "0")))
        fee = Decimal(str(o.get("fee", "0")))
        gas = Decimal(str(o.get("gas", "0")))
        won = res == str(o.get("outcome", "")).upper()
        payout = Decimal(size) if won else Decimal("0")

        total_cost += Decimal(size) * price + fee + gas
        total_payout += payout
        wins += 1 if won else 0
        legs.append({**o, "won": won, "payout": str(payout)})

    expected = Decimal(str(record.get("pi", "0")))

    if pending:
        status, realized = "PENDING", None
    elif wins == 1:
        realized = total_payout - total_cost
        status = "MATCH" if realized >= expected else "MISMATCH"
    else:
        realized = total_payout - total_cost
        status = "SETTLEMENT_CONFLICT"

    return {
        "key": record.get("key"), "ts": record.get("ts"), "status": status,
        "legs": legs,
        "total_cost": str(total_cost), "total_payout": str(total_payout),
        "realized_pnl": str(realized) if realized is not None else None,
        "expected_pi": str(expected),
    }


# ---------- Export CSV laporan klien ----------
def export_csv(settlements: list, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "ts", "status", "total_cost", "total_payout",
                    "realized_pnl", "expected_pi"])
        for s in settlements:
            if s.get("status") == "PENDING":
                continue
            w.writerow([s.get("key"), s.get("ts"), s.get("status"),
                        s.get("total_cost"), s.get("total_payout"),
                        s.get("realized_pnl"), s.get("expected_pi")])
    return path