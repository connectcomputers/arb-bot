"""
Paper Executor — Minggu 7 (MODE AMAN, tidak mengirim order ke bursa).
Menyusun order persis seperti eksekusi asli, lalu mencatatnya ke ledger simulasi.
"""
import json
import time
from dataclasses import dataclass, asdict
from decimal import Decimal
from pathlib import Path
from typing import List

from app.mapper.canonical import MarketInfo
from app.signal.engine import SignalDecision

PAPER_LEDGER = Path("data") / "paper_trades.json"


@dataclass
class PaperOrder:
    venue: str
    market_id: str
    title: str
    side: str       # "BUY"
    outcome: str    # "YES" / "NO"
    price: Decimal
    size: int
    ts: int


def build_paper_orders(market_a: MarketInfo, market_b: MarketInfo,
                       signal: SignalDecision) -> List[PaperOrder]:
    """Susun 2 order (satu per venue) sesuai arah signal."""
    if not signal.execute or signal.direction is None:
        return []
    
    ts = int(time.time())
    orders = []
    
    if signal.direction == "YES_A_NO_B":
        orders.append(PaperOrder(market_a.venue, market_a.venue_id, market_a.title,
                                 "BUY", "YES", market_a.yes_price, signal.size, ts))
        orders.append(PaperOrder(market_b.venue, market_b.venue_id, market_b.title,
                                 "BUY", "NO", market_b.no_price, signal.size, ts))
    else:  # NO_A_YES_B
        orders.append(PaperOrder(market_a.venue, market_a.venue_id, market_a.title,
                                 "BUY", "NO", market_a.no_price, signal.size, ts))
        orders.append(PaperOrder(market_b.venue, market_b.venue_id, market_b.title,
                                 "BUY", "YES", market_b.yes_price, signal.size, ts))
    
    return orders


def save_paper_trade(key_repr: str, orders: List[PaperOrder], pi: Decimal):
    """Catat trade paper ke ledger JSON (append)."""
    PAPER_LEDGER.parent.mkdir(exist_ok=True)
    
    record = {
        "ts": int(time.time()),
        "key": key_repr,
        "pi": str(pi),
        "orders": [asdict(o) for o in orders],
    }
    
    existing = []
    if PAPER_LEDGER.exists():
        try:
            existing = json.loads(PAPER_LEDGER.read_text())
        except Exception:
            existing = []
    
    existing.append(record)
    PAPER_LEDGER.write_text(json.dumps(existing, indent=2, default=str))