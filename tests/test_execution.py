from decimal import Decimal
from app.mapper.canonical import MarketInfo, CanonicalKey
from app.signal.engine import SignalDecision
from app.execution.paper_executor import build_paper_orders


def _mk(venue, yes, no, vid="id1"):
    return MarketInfo(
        venue=venue, venue_id=vid, title="t",
        canonical_key=CanonicalKey("BTC", "UP_DOWN", "15m", None, 9999999999, "d"),
        category="Crypto", series=None, is_parlay=False, is_live_sport=False,
        yes_price=yes, no_price=no, liquidity_usd=None,
        settlement_source="s", raw_data={},
    )


def test_build_orders_yes_a_no_b():
    a = _mk("polymarket", Decimal("0.45"), Decimal("0.55"), "pa")
    b = _mk("kalshi", Decimal("0.50"), Decimal("0.50"), "kb")
    sig = SignalDecision(execute=True, direction="YES_A_NO_B", size=100,
                         gross_discount=Decimal("0.05"), total_fees=Decimal("3"),
                         pi=Decimal("1"), reason="x")
    orders = build_paper_orders(a, b, sig)
    assert len(orders) == 2
    assert orders[0].venue == "polymarket" and orders[0].outcome == "YES"
    assert orders[1].venue == "kalshi" and orders[1].outcome == "NO"


def test_build_orders_tidak_eksekusi_kosong():
    a = _mk("polymarket", Decimal("0.5"), Decimal("0.5"))
    b = _mk("kalshi", Decimal("0.5"), Decimal("0.5"))
    sig = SignalDecision(execute=False, direction=None, size=100,
                         gross_discount=Decimal("0"), total_fees=Decimal("0"),
                         pi=Decimal("-1"), reason="tunggu")
    assert build_paper_orders(a, b, sig) == []