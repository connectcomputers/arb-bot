"""
Integration test: Pipeline Scanner + Mapper + Signal + Paper Executor.
Memastikan seluruh rantai bekerja end-to-end saat signal = 🟢.
"""
from decimal import Decimal
from pathlib import Path
import json
import time

from app.mapper.canonical import MarketInfo, CanonicalKey
from app.signal.engine import evaluate_pair
from app.execution.paper_executor import build_paper_orders, save_paper_trade, PAPER_LEDGER


def _mk(venue, yes, no, vid="id1"):
    return MarketInfo(
        venue=venue, venue_id=vid, title="Integration Test Market",
        canonical_key=CanonicalKey("BTC", "UP_DOWN", "15m", None,
                                   int(time.time()) + 600, "test"),
        category="Crypto", series=None, is_parlay=False, is_live_sport=False,
        yes_price=yes, no_price=no, liquidity_usd=None,
        settlement_source="test", raw_data={},
    )


def test_pipeline_end_to_end_signal_eksekusi():
    """Skenario: diskon besar → signal 🟢 → paper orders tersimpan."""
    # Backup file paper_trades.json jika ada
    backup = None
    if PAPER_LEDGER.exists():
        backup = PAPER_LEDGER.read_text()
        PAPER_LEDGER.unlink()
    
    try:
        # Buat market dengan diskon 5% (cukup besar untuk signal 🟢)
        a = _mk("polymarket", Decimal("0.45"), Decimal("0.55"), "pa")
        b = _mk("kalshi", Decimal("0.50"), Decimal("0.50"), "kb")
        
        # Signal engine harus memutuskan 🟢
        signal = evaluate_pair(a, b, C=100)
        assert signal.execute is True, f"Seharusnya 🟢, dapat {signal.reason}"
        
        # Build paper orders
        orders = build_paper_orders(a, b, signal)
        assert len(orders) == 2, f"Seharusnya 2 order, dapat {len(orders)}"
        
        # Save paper trade
        save_paper_trade("TEST-BTC.15m", orders, signal.pi)
        
        # Verifikasi file JSON tercipta dan valid
        assert PAPER_LEDGER.exists(), "File paper_trades.json harus tercipta"
        data = json.loads(PAPER_LEDGER.read_text())
        assert len(data) >= 1, "Minimal 1 record harus ada"
        last_record = data[-1]
        assert last_record["key"] == "TEST-BTC.15m"
        assert len(last_record["orders"]) == 2
        
    finally:
        # Restore backup (atau hapus file jika tidak ada backup)
        if backup is not None:
            PAPER_LEDGER.write_text(backup)
        elif PAPER_LEDGER.exists():
            PAPER_LEDGER.unlink()