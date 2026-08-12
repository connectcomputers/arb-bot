"""Unit test Settlement & Rekonsiliasi (murni, tanpa network)."""
from decimal import Decimal

from app.settlement import compute_settlement, export_csv


def _record(pi="1.00"):
    # Skenario arbitrase: beli YES di poly, beli NO di kalshi
    # Kalau market resolve YES: poly menang, kalshi kalah → 1 kaki menang
    # cost = (100*0.45 + 1.73 + 0.01) + (100*0.50 + 1.75 + 0) = 98.49
    # payout = 100 (poly menang) + 0 (kalshi kalah) = 100
    # realized = 100 - 98.49 = 1.51
    return {
        "key": "TEST.15m", "ts": 123, "pi": pi,
        "orders": [
            {"venue": "polymarket", "market_id": "pa", "outcome": "YES",
             "price": "0.45", "size": 100, "fee": "1.73", "gas": "0.01"},
            {"venue": "kalshi", "market_id": "kb", "outcome": "NO",
             "price": "0.50", "size": 100, "fee": "1.75", "gas": "0"},
        ],
    }


def test_match_bila_realized_di_atas_expected():
    # Market sama-sama resolve YES (BTC naik)
    # Poly beli YES → menang; Kalshi beli NO → kalah (karena YES bukan NO)
    # wins = 1, realized = 1.51 >= expected 1.00 → MATCH
    res = {("polymarket", "pa"): "YES", ("kalshi", "kb"): "YES"}
    s = compute_settlement(_record(pi="1.00"), res)
    assert s["status"] == "MATCH"
    assert Decimal(s["realized_pnl"]) == Decimal("1.51")


def test_mismatch_bila_expected_terlalu_tinggi():
    # Resolusi sama (kedua YES), tapi expected terlalu tinggi
    res = {("polymarket", "pa"): "YES", ("kalshi", "kb"): "YES"}
    s = compute_settlement(_record(pi="2.00"), res)
    assert s["status"] == "MISMATCH"


def test_conflict_bila_kedua_kaki_kalah():
    # Skenario tidak mungkin dalam arbitrase benar:
    # Poly beli YES kalah (res NO); Kalshi beli NO kalah (res YES)
    # Ini indikasi false-friend (market beda)
    res = {("polymarket", "pa"): "NO", ("kalshi", "kb"): "YES"}
    s = compute_settlement(_record(), res)
    assert s["status"] == "SETTLEMENT_CONFLICT"


def test_pending_bila_resolusi_belum_lengkap():
    res = {("polymarket", "pa"): "YES"}  # kalshi belum settle
    s = compute_settlement(_record(), res)
    assert s["status"] == "PENDING"


def test_export_csv_melewati_pending(tmp_path):
    rows = [
        {"key": "A", "ts": 1, "status": "MATCH", "total_cost": "98.49",
         "total_payout": "100", "realized_pnl": "1.51", "expected_pi": "1.00"},
        {"key": "B", "ts": 2, "status": "PENDING", "total_cost": "0",
         "total_payout": "0", "realized_pnl": None, "expected_pi": "0"},
    ]
    path = export_csv(rows, tmp_path / "lap.csv")
    content = path.read_text()
    assert "A" in content and "B" not in content
    assert content.splitlines()[0].startswith("key,ts,status")