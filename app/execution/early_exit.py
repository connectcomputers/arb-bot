"""
Early-Exit Recycling — Tahap 13-D.
Strategi close posisi terbuka cepat jika salah satu kaki gagal.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from app.execution.base import (
    Executor, OrderRequest, OrderResult, OrderStatus,
    OrderSide, OrderOutcome, OrderType
)
from app.mapper.canonical import MarketInfo


class ExitStrategy(str, Enum):
    REVERSE_SAME_VENUE = "reverse_same_venue"
    CROSS_VENUE_EXIT = "cross_venue_exit"
    MARKET_MAKER_EXIT = "market_maker_exit"
    FAILED = "failed"


@dataclass
class ExitResult:
    """Hasil dari early-exit attempt."""
    strategy: ExitStrategy
    success: bool
    slippage_cost: Decimal = Decimal("0")
    order_result: Optional[OrderResult] = None
    error_message: str = ""
    attempts: int = 0


async def attempt_early_exit(
    market: MarketInfo,
    executor: Executor,
    original_side: OrderSide,
    original_outcome: OrderOutcome,
    size: int,
    max_attempts: int = 3,
    max_slippage_pct: Decimal = Decimal("0.02"),  # 2% max slippage
) -> ExitResult:
    """
    Coba close posisi terbuka dengan strategi terbaik.
    
    Returns:
        ExitResult dengan strategy yang dipakai + slippage cost
    """
    # Strategi 1: Reverse order di venue yang sama (paling murah)
    reverse_side = OrderSide.SELL if original_side == OrderSide.BUY else OrderSide.BUY
    
    for attempt in range(max_attempts):
        # Coba reverse dengan harga yang sedikit lebih buruk (untuk instant fill)
        slippage = Decimal("0.01") * (attempt + 1)  # 1%, 2%, 3%
        
        if slippage > max_slippage_pct:
            break  # Jangan exceed max slippage
        
        if reverse_side == OrderSide.SELL:
            # Jual posisi YES/NO dengan harga lebih rendah dari market
            exit_price = Decimal("0.01") + (slippage * Decimal("0.5"))
        else:
            # Beli balik posisi dengan harga lebih tinggi
            exit_price = Decimal("0.99") - (slippage * Decimal("0.5"))
        
        req = OrderRequest(
            venue=market.venue,
            market_id=market.venue_id,
            side=reverse_side,
            outcome=original_outcome,
            price=exit_price,
            size=size,
            order_type=OrderType.IOC,
            worst_price=exit_price,
            idempotency_key=f"{market.venue_id}-exit-{attempt}",
        )
        
        result = await executor.submit_order(req)
        
        if result.is_success:
            # Hitung slippage cost (perbedaan harga dari original)
            slippage_cost = abs(exit_price - (result.filled_price or exit_price)) * size
            return ExitResult(
                strategy=ExitStrategy.REVERSE_SAME_VENUE,
                success=True,
                slippage_cost=slippage_cost,
                order_result=result,
                attempts=attempt + 1,
            )
    
    # Semua attempt gagal
    return ExitResult(
        strategy=ExitStrategy.FAILED,
        success=False,
        error_message=f"Gagal close setelah {max_attempts} attempts",
        attempts=max_attempts,
    )


async def attempt_cross_venue_exit(
    original_market: MarketInfo,
    alternative_venues: list[MarketInfo],
    executors: dict[str, Executor],
    original_side: OrderSide,
    original_outcome: OrderOutcome,
    size: int,
) -> ExitResult:
    """
    Coba close posisi di venue lain yang punya market yang sama.
    
    Contoh: Posisi YES di Kalshi, coba sell NO di Polymarket (jika market sama).
    """
    for alt_market in alternative_venues:
        if alt_market.venue == original_market.venue:
            continue  # Skip venue yang sama
        
        # Cek apakah market ini benar-benar sama (canonical key match)
        if alt_market.canonical_key != original_market.canonical_key:
            continue
        
        executor = executors.get(alt_market.venue)
        if not executor:
            continue
        
        # Ambil posisi berlawanan (cross-venue hedge)
        cross_side = OrderSide.BUY if original_side == OrderSide.BUY else OrderSide.SELL
        cross_outcome = OrderOutcome.NO if original_outcome == OrderOutcome.YES else OrderOutcome.YES
        
        # Harga yang agak konservatif untuk instant fill
        cross_price = Decimal("0.50")  # Neutral price
        
        req = OrderRequest(
            venue=alt_market.venue,
            market_id=alt_market.venue_id,
            side=cross_side,
            outcome=cross_outcome,
            price=cross_price,
            size=size,
            order_type=OrderType.FOK,
            idempotency_key=f"{alt_market.venue_id}-cross-exit",
        )
        
        result = await executor.submit_order(req)
        
        if result.is_success:
            # Hitung slippage (perbedaan dari ideal hedge)
            slippage_cost = Decimal("0.02") * size  # Estimasi 2% slippage
            
            return ExitResult(
                strategy=ExitStrategy.CROSS_VENUE_EXIT,
                success=True,
                slippage_cost=slippage_cost,
                order_result=result,
                attempts=1,
            )
    
    return ExitResult(
        strategy=ExitStrategy.FAILED,
        success=False,
        error_message="Tidak ada venue alternatif yang cocok",
        attempts=0,
    )