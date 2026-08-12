"""
Maker Strategy — Tahap 13-B.
Logika pemilihan maker vs taker berdasarkan time-sensitivity.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class OrderStrategy(str, Enum):
    TAKER_ONLY = "taker_only"
    MAKER_ONLY = "maker_only"
    MAKER_WITH_FALLBACK = "maker_with_fallback"


@dataclass
class StrategyDecision:
    strategy: OrderStrategy
    maker_timeout_sec: int = 30
    fee_savings_pct: Decimal = Decimal("0")
    reason: str = ""


def decide_strategy(
    ttl_seconds: int,
    template: str,
    venue: str,
) -> StrategyDecision:
    """
    Tentukan strategi (maker/taker) berdasarkan time-sensitivity.
    
    Rules:
    - TTL < 600 detik → TAKER_ONLY
    - Template UP_DOWN dengan TTL panjang → MAKER_WITH_FALLBACK
    - Template lain (ABOVE_STRIKE, YES_NO_EVENT) → MAKER_WITH_FALLBACK
    """
    if ttl_seconds < 600:
        return StrategyDecision(
            strategy=OrderStrategy.TAKER_ONLY,
            maker_timeout_sec=0,
            fee_savings_pct=Decimal("0"),
            reason=f"TTL {ttl_seconds}s < 600s threshold",
        )
    
    return StrategyDecision(
        strategy=OrderStrategy.MAKER_WITH_FALLBACK,
        maker_timeout_sec=30 if template == "UP_DOWN" else 60,
        fee_savings_pct=_estimate_savings(venue),
        reason=f"Template {template}, TTL {ttl_seconds}s, coba maker",
    )


def _estimate_savings(venue: str) -> Decimal:
    savings_map = {
        "kalshi": Decimal("0.75"),
        "polymarket": Decimal("0.50"),
        "limitless": Decimal("1.00"),
    }
    return savings_map.get(venue.lower(), Decimal("0"))