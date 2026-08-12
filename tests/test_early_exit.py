"""Unit test Early-Exit Recycling (Tahap 13-D)."""
import pytest
from decimal import Decimal
import time

from app.execution.early_exit import (
    attempt_early_exit, attempt_cross_venue_exit, ExitStrategy
)
from app.execution.base import OrderSide, OrderOutcome, OrderResult, OrderStatus
from app.execution.kalshi_executor import KalshiExecutor
from app.execution.polymarket_executor import PolymarketExecutor
from app.mapper.canonical import MarketInfo, CanonicalKey


def _mk(venue, yes, no, vid, asset="BTC", template="UP_DOWN", interval="1h"):
    return MarketInfo(
        venue=venue, venue_id=vid, title="Test",
        canonical_key=CanonicalKey(asset, template, interval, None,
                                   int(time.time()) + 3600, "t"),
        category="Crypto", series=None, is_parlay=False, is_live_sport=False,
        yes_price=yes, no_price=no, liquidity_usd=None,
        settlement_source="s", raw_data={},
    )


@pytest.mark.asyncio
async def test_early_exit_success_first_attempt():
    """Early exit berhasil di attempt pertama."""
    market = _mk("kalshi", Decimal("0.45"), Decimal("0.55"), "test1")
    executor = KalshiExecutor(live=False)
    
    result = await attempt_early_exit(
        market=market,
        executor=executor,
        original_side=OrderSide.BUY,
        original_outcome=OrderOutcome.YES,
        size=100,
        max_attempts=3,
    )
    
    assert result.success is True
    assert result.strategy == ExitStrategy.REVERSE_SAME_VENUE
    assert result.attempts == 1
    assert result.slippage_cost >= 0


@pytest.mark.asyncio
async def test_early_exit_multiple_attempts():
    """Early exit butuh beberapa attempt (simulasi)."""
    market = _mk("kalshi", Decimal("0.45"), Decimal("0.55"), "test2")
    
    # Buat executor custom yang reject 2x pertama, success di attempt 3
    class FailTwiceExecutor(KalshiExecutor):
        def __init__(self):
            super().__init__(live=False)
            self.call_count = 0
        
        async def submit_order(self, request):
            self.call_count += 1
            if self.call_count <= 2:
                return OrderResult(
                    order_id="", status=OrderStatus.REJECTED,
                    error_message="rejected", timestamp=int(time.time())
                )
            return await super().submit_order(request)
    
    executor = FailTwiceExecutor()
    
    result = await attempt_early_exit(
        market=market,
        executor=executor,
        original_side=OrderSide.BUY,
        original_outcome=OrderOutcome.YES,
        size=100,
        max_attempts=3,
        max_slippage_pct=Decimal("0.05"),  # FIX: naikkan dari 0.02 → 0.05 agar 3 attempts tercapai
    )
    
    assert result.success is True
    assert result.attempts == 3


@pytest.mark.asyncio
async def test_early_exit_exceeds_max_slippage():
    """Early exit stop jika slippage exceed max."""
    market = _mk("kalshi", Decimal("0.45"), Decimal("0.55"), "test3")
    
    # Executor yang selalu reject
    class AlwaysRejectExecutor(KalshiExecutor):
        async def submit_order(self, request):
            return OrderResult(
                order_id="", status=OrderStatus.REJECTED,
                error_message="no liquidity", timestamp=int(time.time())
            )
    
    executor = AlwaysRejectExecutor()
    
    result = await attempt_early_exit(
        market=market,
        executor=executor,
        original_side=OrderSide.BUY,
        original_outcome=OrderOutcome.YES,
        size=100,
        max_attempts=3,
        max_slippage_pct=Decimal("0.02"),
    )
    
    assert result.success is False
    assert result.strategy == ExitStrategy.FAILED


@pytest.mark.asyncio
async def test_cross_venue_exit_no_alternative():
    """Cross-venue exit gagal jika tidak ada venue alternatif."""
    market1 = _mk("kalshi", Decimal("0.45"), Decimal("0.55"), "k1")
    
    result = await attempt_cross_venue_exit(
        original_market=market1,
        alternative_venues=[],
        executors={},
        original_side=OrderSide.BUY,
        original_outcome=OrderOutcome.YES,
        size=100,
    )
    
    assert result.success is False
    assert result.strategy == ExitStrategy.FAILED
    assert "alternatif" in result.error_message


@pytest.mark.asyncio
async def test_cross_venue_exit_with_matching_market():
    """Cross-venue exit berhasil jika ada venue lain dengan market sama."""
    # Market Kalshi
    market_kalshi = _mk("kalshi", Decimal("0.45"), Decimal("0.55"), "k1")
    
    # Market Polymarket dengan canonical key SAMA
    market_poly = MarketInfo(
        venue="polymarket",
        venue_id="p1",
        title="Test Poly",
        canonical_key=market_kalshi.canonical_key,  # SAMA (reference)
        category="Crypto",
        series=None,
        is_parlay=False,
        is_live_sport=False,
        yes_price=Decimal("0.46"),
        no_price=Decimal("0.54"),
        liquidity_usd=None,
        settlement_source="s",
        raw_data={},
    )
    
    # FIX: pakai PolymarketExecutor, bukan KalshiExecutor
    executor_poly = PolymarketExecutor(live=False)
    
    result = await attempt_cross_venue_exit(
        original_market=market_kalshi,
        alternative_venues=[market_poly],
        executors={"polymarket": executor_poly},
        original_side=OrderSide.BUY,
        original_outcome=OrderOutcome.YES,
        size=100,
    )
    
    assert result.success is True
    assert result.strategy == ExitStrategy.CROSS_VENUE_EXIT
    assert result.attempts == 1


def test_exit_strategy_enum_values():
    """ExitStrategy enum harus punya value yang benar."""
    assert ExitStrategy.REVERSE_SAME_VENUE.value == "reverse_same_venue"
    assert ExitStrategy.CROSS_VENUE_EXIT.value == "cross_venue_exit"
    assert ExitStrategy.FAILED.value == "failed"