"""Unit test Executor Asli + Leg Manager."""
import pytest
from decimal import Decimal

from app.execution.base import (
    OrderRequest, OrderResult, OrderStatus, OrderSide, OrderOutcome, OrderType
)
from app.execution.kalshi_executor import KalshiExecutor
from app.execution.leg_manager import LegManager, ArbState
from app.mapper.canonical import MarketInfo, CanonicalKey
from app.signal.engine import SignalDecision


def _mk(venue, yes, no, vid="id1"):
    return MarketInfo(
        venue=venue, venue_id=vid, title="Test Market",
        canonical_key=CanonicalKey("BTC", "UP_DOWN", "15m", None, 9999999999, "t"),
        category="Crypto", series=None, is_parlay=False, is_live_sport=False,
        yes_price=yes, no_price=no, liquidity_usd=None,
        settlement_source="s", raw_data={},
    )


# ============ KALSHI EXECUTOR ============
@pytest.mark.asyncio
async def test_kalshi_sim_fill():
    """Mode simulasi: order fill penuh di worst_price."""
    ex = KalshiExecutor(live=False)
    req = OrderRequest(
        venue="kalshi", market_id="KXBTC-26AUG", side=OrderSide.BUY,
        outcome=OrderOutcome.YES, price=Decimal("0.50"), size=100,
        worst_price=Decimal("0.51"),
    )
    res = await ex.submit_order(req)
    assert res.is_success
    assert res.filled_size == 100
    assert res.filled_price == Decimal("0.51")  # worst_price dipakai


@pytest.mark.asyncio
async def test_kalshi_sim_venue_mismatch():
    """Order dengan venue salah → REJECTED."""
    ex = KalshiExecutor(live=False)
    req = OrderRequest(
        venue="polymarket", market_id="abc", side=OrderSide.BUY,
        outcome=OrderOutcome.YES, price=Decimal("0.50"), size=100,
    )
    res = await ex.submit_order(req)
    assert res.status == OrderStatus.REJECTED
    assert "mismatch" in res.error_message.lower()


@pytest.mark.asyncio
async def test_kalshi_balance_sim():
    ex = KalshiExecutor(live=False)
    bal = await ex.get_balance()
    assert bal["venue"] == "kalshi"
    assert bal["simulated"] is True


# ============ LEG MANAGER ============
@pytest.mark.asyncio
async def test_leg_mgr_both_fill():
    """Kedua kaki fill → state COMPLETED."""
    a = _mk("kalshi", Decimal("0.45"), Decimal("0.55"), "a")
    b = _mk("kalshi", Decimal("0.50"), Decimal("0.50"), "b")
    ex_a = KalshiExecutor(live=False)
    ex_b = KalshiExecutor(live=False)
    mgr = LegManager(ex_a, ex_b)

    signal = SignalDecision(
        execute=True, direction="YES_A_NO_B", size=100,
        gross_discount=Decimal("0.05"), total_fees=Decimal("3"),
        pi=Decimal("1"), reason="ok",
    )
    rec = await mgr.execute_pair(a, b, signal)

    assert rec.state == ArbState.COMPLETED
    assert rec.leg1_result.is_success
    assert rec.leg2_result.is_success


@pytest.mark.asyncio
async def test_leg_mgr_signal_not_execute():
    """Signal.execute = False → state FAILED dengan reason."""
    a = _mk("kalshi", Decimal("0.5"), Decimal("0.5"))
    b = _mk("kalshi", Decimal("0.5"), Decimal("0.5"))
    mgr = LegManager(KalshiExecutor(live=False), KalshiExecutor(live=False))
    signal = SignalDecision(execute=False, direction=None, size=100,
                            gross_discount=Decimal("0"), total_fees=Decimal("0"),
                            pi=Decimal("-1"), reason="tunggu")
    rec = await mgr.execute_pair(a, b, signal)
    assert rec.state == ArbState.FAILED
    assert "tidak execute" in rec.error_message


@pytest.mark.asyncio
async def test_leg_mgr_alert_called_on_hedge_failure():
    """Kalau hedge gagal, alert_fn dipanggil dengan pesan kritis."""
    alerts_received = []

    async def fake_alert(text):
        alerts_received.append(text)
        return True

    # Buat executor yang selalu reject leg 2, dan reject hedge
    class FailOnSecond:
        def __init__(self, fail_on_leg2=False, fail_hedge=True):
            self.venue_name = "test"
            self.live = False
            self.call_count = 0
            self.fail_on_leg2 = fail_on_leg2
            self.fail_hedge = fail_hedge

        async def submit_order(self, request: OrderRequest) -> OrderResult:
            self.call_count += 1
            # Leg 2: order ke-1, Hedge: order ke-2+
            if self.call_count == 1 and not self.fail_on_leg2:
                return OrderResult(order_id="ok1", status=OrderStatus.FILLED,
                                   filled_size=100, timestamp=1)
            if self.fail_hedge or (self.fail_on_leg2 and self.call_count == 1):
                return OrderResult(order_id="", status=OrderStatus.REJECTED,
                                   error_message="rejected", timestamp=1)
            return OrderResult(order_id="ok", status=OrderStatus.FILLED,
                               filled_size=100, timestamp=1)

        async def cancel_order(self, _id): return True
        async def get_balance(self): return {"venue": "test", "available": Decimal("0")}

    # Executor A: leg 1 fill, hedge fail (call_count 1 = fill, 2+ = fail)
    # Executor B: leg 2 reject
    ex_a = FailOnSecond(fail_on_leg2=False, fail_hedge=True)
    ex_b = FailOnSecond(fail_on_leg2=True, fail_hedge=True)

    mgr = LegManager(ex_a, ex_b, alert_fn=fake_alert)
    a = _mk("test", Decimal("0.45"), Decimal("0.55"), "a")
    b = _mk("test", Decimal("0.50"), Decimal("0.50"), "b")
    signal = SignalDecision(execute=True, direction="YES_A_NO_B", size=100,
                            gross_discount=Decimal("0.05"), total_fees=Decimal("3"),
                            pi=Decimal("1"), reason="ok")

    rec = await mgr.execute_pair(a, b, signal)
    assert rec.state == ArbState.FAILED
    assert "CRITICAL" in rec.error_message
    assert len(alerts_received) == 1
    assert "LEG RISK CRITICAL" in alerts_received[0]

# ============ POLYMARKET EXECUTOR ============
@pytest.mark.asyncio
async def test_polymarket_sim_fill():
    from app.execution.polymarket_executor import PolymarketExecutor
    ex = PolymarketExecutor(live=False)
    req = OrderRequest(
        venue="polymarket", market_id="abc123", side=OrderSide.BUY,
        outcome=OrderOutcome.YES, price=Decimal("0.50"), size=100,
        worst_price=Decimal("0.52"),
    )
    res = await ex.submit_order(req)
    assert res.is_success
    assert res.filled_price == Decimal("0.52")


@pytest.mark.asyncio
async def test_polymarket_sim_venue_mismatch():
    from app.execution.polymarket_executor import PolymarketExecutor
    ex = PolymarketExecutor(live=False)
    req = OrderRequest(
        venue="kalshi", market_id="abc", side=OrderSide.BUY,
        outcome=OrderOutcome.YES, price=Decimal("0.50"), size=100,
    )
    res = await ex.submit_order(req)
    assert res.status == OrderStatus.REJECTED


# ============ LIMITLESS EXECUTOR ============
@pytest.mark.asyncio
async def test_limitless_sim_fill():
    from app.execution.limitless_executor import LimitlessExecutor
    ex = LimitlessExecutor(live=False)
    req = OrderRequest(
        venue="limitless", market_id="xyz789", side=OrderSide.BUY,
        outcome=OrderOutcome.YES, price=Decimal("0.50"), size=100,
    )
    res = await ex.submit_order(req)
    assert res.is_success


# ============ FACTORY ============
def test_factory_kalshi():
    from app.execution.factory import get_executor
    ex = get_executor("kalshi", live=False)
    assert ex.venue_name == "kalshi"


def test_factory_polymarket():
    from app.execution.factory import get_executor
    ex = get_executor("POLYMARKET", live=False)
    assert ex.venue_name == "polymarket"


def test_factory_unknown_venue_raises():
    from app.execution.factory import get_executor
    with pytest.raises(ValueError):
        get_executor("unknown_venue")    