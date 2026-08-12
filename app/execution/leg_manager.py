"""
Leg Manager — orkestrator arbitrase 2-kaki dengan leg-risk management.

State machine:
  IDLE → LEG1_SUBMITTED → LEG1_FILLED → LEG2_SUBMITTED
       → (kalau LEG2 rejected) → HEDGE_ATTEMPTED → FAILED
       → (kalau LEG2 filled) → COMPLETED
"""
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from app.execution.base import (
    Executor, OrderRequest, OrderResult, OrderStatus,
    OrderSide, OrderOutcome, OrderType
)
from app.mapper.canonical import MarketInfo
from app.signal.engine import SignalDecision

LEG2_TIMEOUT_SEC = 5          # waktu max tunggu kaki 2
HEDGE_ATTEMPTS = 2            # berapa kali coba hedge


class ArbState(str, Enum):
    IDLE = "idle"
    LEG1_SUBMITTED = "leg1_submitted"
    LEG1_FILLED = "leg1_filled"
    LEG2_SUBMITTED = "leg2_submitted"
    COMPLETED = "completed"
    HEDGE_ATTEMPTED = "hedge_attemptd"
    FAILED = "failed"


@dataclass
class ArbExecution:
    """Record satu eksekusi arbitrase."""
    key: str
    state: ArbState = ArbState.IDLE
    leg1_result: Optional[OrderResult] = None
    leg2_result: Optional[OrderResult] = None
    hedge_results: list = field(default_factory=list)
    error_message: Optional[str] = None
    started_ts: int = 0
    completed_ts: int = 0


class LegManager:
    """Orkestrator 2-kaki dengan risk management."""

    def __init__(self, executor_a: Executor, executor_b: Executor,
                 alert_fn=None):
        self.executor_a = executor_a
        self.executor_b = executor_b
        self.alert_fn = alert_fn  # async fn untuk kirim alert Telegram
        self.history: list[ArbExecution] = []

    # async def execute_pair(self, market_a: MarketInfo, market_b: MarketInfo,
    #                         signal: SignalDecision) -> ArbExecution:
    async def execute_pair(self, market_a: MarketInfo, market_b: MarketInfo,
                            signal: SignalDecision,
                            use_maker_strategy: bool = False) -> ArbExecution:
        """Eksekusi satu pasangan arbitrase."""
        exec_rec = ArbExecution(key=str(getattr(market_a.canonical_key, 'asset', 'unknown')),
                                started_ts=int(time.time()))
        self.history.append(exec_rec)

        if not signal.execute or signal.direction is None:
            exec_rec.state = ArbState.FAILED
            exec_rec.error_message = f"Signal tidak execute: {signal.reason}"
            return exec_rec

        # Tentukan kaki 1 dan kaki 2 dari signal.direction
        if signal.direction == "YES_A_NO_B":
            leg1 = (market_a, self.executor_a, OrderSide.BUY, OrderOutcome.YES,
                    market_a.yes_price)
            leg2 = (market_b, self.executor_b, OrderSide.BUY, OrderOutcome.NO,
                    market_b.no_price)
        else:  # NO_A_YES_B
            leg1 = (market_a, self.executor_a, OrderSide.BUY, OrderOutcome.NO,
                    market_a.no_price)
            leg2 = (market_b, self.executor_b, OrderSide.BUY, OrderOutcome.YES,
                    market_b.yes_price)

        # === LEG 1 ===
        exec_rec.state = ArbState.LEG1_SUBMITTED
        m1, ex1, side1, out1, price1 = leg1

        # === MAKER STRATEGY (Tahap 13-B) ===
        from app.execution.maker_strategy import decide_strategy, OrderStrategy
        import time as _time
        import asyncio as _asyncio
        
        now_ts = int(_time.time())
        ttl_sec = max(0, m1.canonical_key.close_ts - now_ts)
        template = m1.canonical_key.template
        
        order_type1 = OrderType.FOK
        if use_maker_strategy:
            leg1_strategy = decide_strategy(ttl_sec, template, m1.venue)
            if leg1_strategy.strategy != OrderStrategy.TAKER_ONLY:
                order_type1 = OrderType.GTC
        
        req1 = OrderRequest(
            venue=m1.venue, market_id=m1.venue_id,
            side=side1, outcome=out1,
            price=price1, size=signal.size,
            order_type=OrderType.FOK,
            worst_price=price1,
            idempotency_key=f"{exec_rec.started_ts}-leg1",
        )
        exec_rec.leg1_result = await ex1.submit_order(req1)

        # Kalau GTC + belum final, tunggu 30 detik lalu fallback ke FOK
        if use_maker_strategy and order_type1 == OrderType.GTC and not exec_rec.leg1_result.is_final:
            await _asyncio.sleep(30)
            if not exec_rec.leg1_result.is_final:
                await ex1.cancel_order(exec_rec.leg1_result.order_id)
                req1.order_type = OrderType.FOK
                exec_rec.leg1_result = await ex1.submit_order(req1)
                
        if not exec_rec.leg1_result.is_success:
            exec_rec.state = ArbState.FAILED
            exec_rec.error_message = f"Leg 1 gagal: {exec_rec.leg1_result.error_message or exec_rec.leg1_result.status.value}"
            return exec_rec

        # === LEG 2 (dengan timeout) ===
        exec_rec.state = ArbState.LEG1_FILLED
        m2, ex2, side2, out2, price2 = leg2
        
        # req2 = OrderRequest(
        #     venue=m2.venue, market_id=m2.venue_id,
        #     side=side2, outcome=out2,
        #     price=price2, size=signal.size,
        #     order_type=OrderType.FOK,
        #     worst_price=price2,
        #     idempotency_key=f"{exec_rec.started_ts}-leg2",
        # )
        # exec_rec.state = ArbState.LEG2_SUBMITTED
        # exec_rec.leg2_result = await ex2.submit_order(req2)

        # === MAKER STRATEGY untuk Leg 2 ===
        order_type2 = OrderType.FOK
        if use_maker_strategy:
            leg2_strategy = decide_strategy(ttl_sec, template, m2.venue)
            if leg2_strategy.strategy != OrderStrategy.TAKER_ONLY:
                order_type2 = OrderType.GTC
        
        req2 = OrderRequest(
            venue=m2.venue, market_id=m2.venue_id,
            side=side2, outcome=out2,
            price=price2, size=signal.size,
            order_type=order_type2,
            worst_price=price2,
            idempotency_key=f"{exec_rec.started_ts}-leg2",
        )
        exec_rec.state = ArbState.LEG2_SUBMITTED
        exec_rec.leg2_result = await ex2.submit_order(req2)
        
        # Kalau GTC + belum final, tunggu 30 detik lalu fallback
        if use_maker_strategy and order_type2 == OrderType.GTC and not exec_rec.leg2_result.is_final:
            await _asyncio.sleep(30)
            if not exec_rec.leg2_result.is_final:
                await ex2.cancel_order(exec_rec.leg2_result.order_id)
                req2.order_type = OrderType.FOK
                exec_rec.leg2_result = await ex2.submit_order(req2)
                
        if exec_rec.leg2_result.is_success:
            # SUKSES! Kedua kaki fill
            exec_rec.state = ArbState.COMPLETED
            exec_rec.completed_ts = int(time.time())
            return exec_rec

        # === LEG 2 GAGAL → HEDGE (coba close leg 1) ===
        exec_rec.state = ArbState.HEDGE_ATTEMPTED
        await self._hedge_leg1(exec_rec, m1, ex1, side1, out1, signal.size)
        return exec_rec

    async def _hedge_leg1(self, exec_rec: ArbExecution,
                          market: MarketInfo, executor: Executor,
                          original_side: OrderSide, outcome: OrderOutcome,
                          size: int):
        """Coba close posisi leg 1 (reverse order)."""
        reverse_side = OrderSide.SELL if original_side == OrderSide.BUY else OrderSide.BUY

        for attempt in range(HEDGE_ATTEMPTS):
            hedge_req = OrderRequest(
                venue=market.venue, market_id=market.venue_id,
                side=reverse_side, outcome=outcome,
                price=Decimal("0.01") if reverse_side == OrderSide.SELL else Decimal("0.99"),
                size=size,
                order_type=OrderType.IOC,
                idempotency_key=f"{exec_rec.started_ts}-hedge-{attempt}",
            )
            hedge_result = await executor.submit_order(hedge_req)
            exec_rec.hedge_results.append(hedge_result)

            if hedge_result.is_success:
                exec_rec.state = ArbState.FAILED
                exec_rec.error_message = (f"Leg 2 gagal, leg 1 berhasil di-hedge "
                                          f"(attempt {attempt + 1})")
                return

        # SEMUA HEDGE GAGAL → INI BAHAYA! Posisi terbuka.
        exec_rec.state = ArbState.FAILED
        exec_rec.error_message = (f"CRITICAL: Leg 2 gagal, hedge gagal {HEDGE_ATTEMPTS}x. "
                                  f"Posisi terbuka di {market.venue}!")

        # Kirim alert Telegram darurat
        if self.alert_fn:
            try:
                await self.alert_fn(
                    f"🚨 <b>LEG RISK CRITICAL</b>\n"
                    f"Key: {exec_rec.key}\n"
                    f"Leg 1: FILLED di {market.venue}\n"
                    f"Leg 2: REJECTED\n"
                    f"Hedge: GAGAL {HEDGE_ATTEMPTS}x\n\n"
                    f"<b>POSISI TERBUKA! INTERVENSI MANUAL DIPERLUKAN!</b>"
                )
            except Exception:
                pass