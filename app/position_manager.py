"""Auto-close posisi yang sudah resolve + tracking untuk P/L."""
import json
import time
from pathlib import Path

POSITIONS_FILE = Path("data/open_positions.json")

def load_positions():
    if POSITIONS_FILE.exists():
        try:
            return json.loads(POSITIONS_FILE.read_text())
        except Exception:
            pass
    return []

def save_positions(positions):
    POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS_FILE.write_text(json.dumps(positions, indent=2))

def track_new_position(venue, market_id, buy_price, size, direction="YES"):
    """Catat posisi baru setelah eksekusi order real."""
    positions = load_positions()
    positions.append({
        "venue": venue,
        "market_id": market_id,
        "buy_price": buy_price,
        "size": size,
        "direction": direction,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "resolved": False,
        "pnl": 0.0,
        "resolved_ts": None,
        "outcome": None,
    })
    save_positions(positions)

def _check_resolved(venue, market_id, creds):
    """Return (resolved: bool, outcome: str|None)."""
    try:
        import httpx
        if venue == "polymarket":
            url = f"https://clob.polymarket.com/markets/{market_id}"
            r = httpx.get(url, timeout=10)
            if r.status_code == 200:
                d = r.json()
                if d.get("closed") or d.get("resolved"):
                    return True, (d.get("outcome") or d.get("resolution_source") or "UNKNOWN")
            return False, None
        elif venue == "kalshi":
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{market_id}"
            r = httpx.get(url, timeout=10)
            if r.status_code == 200:
                m = r.json().get("market", {})
                if m.get("status") == "settled":
                    return True, m.get("result", "UNKNOWN")
            return False, None
        elif venue == "limitless":
            return False, None  # SDK belum expose status resolve sederhana
    except Exception:
        pass
    return False, None

def _pnl_of(pos, outcome):
    """Hitung P/L: menang = (1 - buy) * size; kalah = -size; unknown = 0."""
    bp = pos.get("buy_price", 0.0) or 0.0
    sz = pos.get("size", 0.0) or 0.0
    dr = (pos.get("direction") or "YES").upper()
    if outcome is None or outcome == "UNKNOWN":
        return 0.0
    win = (dr == "YES" and outcome == "YES") or (dr == "NO" and outcome == "NO")
    return round(((1.0 - bp) * sz) if win else (-sz), 4)

def check_and_close_positions():
    """Cek posisi terbuka, tandai resolve, hitung P/L. Tidak memanggil redeem (aman)."""
    from app.config_store import load_creds
    try:
        from app.engine import _log_loop
    except Exception:
        _log_loop = lambda msg: None

    positions = load_positions()
    if not positions:
        return

    creds = load_creds()
    updated = False
    closed_count = 0
    total_pnl = 0.0

    for pos in positions:
        if pos.get("resolved"):
            continue
        venue = pos.get("venue")
        mid = pos.get("market_id")
        resolved, outcome = _check_resolved(venue, mid, creds.get(venue, {}))
        if resolved:
            pos["resolved"] = True
            pos["outcome"] = outcome
            pos["resolved_ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            pos["pnl"] = _pnl_of(pos, outcome)
            closed_count += 1
            total_pnl += pos["pnl"]
            updated = True
            _log_loop(f"position resolved: {venue} {mid} outcome={outcome} P/L=${pos['pnl']:.2f}")

    if updated:
        save_positions(positions)
        if closed_count:
            _log_loop(f"positions resolved: {closed_count}, total P/L=${total_pnl:.2f}")
