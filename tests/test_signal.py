from decimal import Decimal
from app.mapper.canonical import MarketInfo, CanonicalKey
from app.signal.engine import evaluate_pair


def _mk(venue, yes, no, category="Crypto", series=None):
    return MarketInfo(
        venue=venue, venue_id="x", title="t",
        canonical_key=CanonicalKey("BTC", "UP_DOWN", "15m", None, 9999999999, "d"),
        category=category, series=series, is_parlay=False, is_live_sport=False,
        yes_price=yes, no_price=no, liquidity_usd=None,
        settlement_source="s", raw_data={},
    )


def test_signal_eksekusi_ketika_diskon_besar():
    # Poly YES 0.45 + Kalshi NO 0.50 = 0.95 → diskon 5¢ > fee ~3.5¢ → untung
    a = _mk("polymarket", Decimal("0.45"), Decimal("0.55"))
    b = _mk("kalshi", Decimal("0.50"), Decimal("0.50"))
    d = evaluate_pair(a, b, C=100)
    assert d.execute is True


def test_signal_tunggu_ketika_diskon_kecil():
    # 0.495 + 0.505 = 1.00 → tidak ada diskon → rugi karena fee
    a = _mk("polymarket", Decimal("0.495"), Decimal("0.505"))
    b = _mk("kalshi", Decimal("0.495"), Decimal("0.505"))
    d = evaluate_pair(a, b, C=100)
    assert d.execute is False


def test_signal_memilih_arah_terbaik():
    # Arah yang untung: NO_A (0.45) + YES_B (0.50) = 0.95
    a = _mk("polymarket", Decimal("0.55"), Decimal("0.45"))
    b = _mk("kalshi", Decimal("0.50"), Decimal("0.50"))
    d = evaluate_pair(a, b, C=100)
    assert d.direction == "NO_A_YES_B"
    assert d.execute is True