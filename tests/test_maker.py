"""Unit test Maker Strategy (Tahap 13-B)."""
import pytest
from decimal import Decimal
import time

from app.execution.maker_strategy import (
    decide_strategy, OrderStrategy, _estimate_savings
)
from app.execution.kalshi_executor import KalshiExecutor
from app.execution.leg_manager import LegManager
from app.mapper.canonical import MarketInfo, CanonicalKey
from app.signal.engine import SignalDecision


def test_taker_only_bila_ttl_pendek():
    """TTL < 600 detik → wajib taker."""
    decision = decide_strategy(ttl_seconds=300, template="UP_DOWN", venue="kalshi")
    assert decision.strategy == OrderStrategy.TAKER_ONLY
    assert decision.maker_timeout_sec == 0


def test_maker_bila_ttl_panjang_crypto_up_down():
    """TTL > 600 detik + UP_DOWN → coba maker dengan fallback."""
    decision = decide_strategy(ttl_seconds=3600, template="UP_DOWN", venue="kalshi")
    assert decision.strategy == OrderStrategy.MAKER_WITH_FALLBACK
    assert decision.maker_timeout_sec == 30
    assert decision.fee_savings_pct == Decimal("0.75")


def test_maker_bila_politics():
    """Politics (YES_NO_EVENT) → selalu boleh maker."""
    decision = decide_strategy(ttl_seconds=86400, template="YES_NO_EVENT", venue="polymarket")
    assert decision.strategy == OrderStrategy.MAKER_WITH_FALLBACK
    assert decision.maker_timeout_sec == 60
    assert decision.fee_savings_pct == Decimal("0.50")


def test_maker_bila_economics_limitless():
    """Economics di Limitless → savings 100%."""
    decision = decide_strategy(ttl_seconds=604800, template="YES_NO_EVENT", venue="limitless")
    assert decision.strategy == OrderStrategy.MAKER_WITH_FALLBACK
    assert decision.fee_savings_pct == Decimal("1.00")


def test_estimate_savings_per_venue():
    """Estimasi savings per venue benar."""
    assert _estimate_savings("kalshi") == Decimal("0.75")
    assert _estimate_savings("polymarket") == Decimal("0.50")
    assert _estimate_savings("limitless") == Decimal("1.00")
    assert _estimate_savings("unknown") == Decimal("0")


def test_reason_message_informatif():
    """Reason message harus menjelaskan keputusan."""
    decision = decide_strategy(ttl_seconds=300, template="UP_DOWN", venue="kalshi")
    assert "TTL" in decision.reason
    assert "threshold" in decision.reason


@pytest.mark.asyncio
async def test_leg_mgr_with_maker_strategy():
    """Leg manager dengan use_maker_strategy=True harus jalan tanpa error."""
    def _mk(venue, yes, no, vid):
        return MarketInfo(
            venue=venue, venue_id=vid, title="Test",
            canonical_key=CanonicalKey("BTC", "YES_NO_EVENT", "daily", None,
                                       int(time.time()) + 3600, "t"),
            category="Crypto", series=None, is_parlay=False, is_live_sport=False,
            yes_price=yes, no_price=no, liquidity_usd=None,
            settlement_source="s", raw_data={},
        )

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

    rec = await mgr.execute_pair(a, b, signal, use_maker_strategy=True)
    assert rec.state.value in ("completed", "failed")