"""
Signal Engine (Π-gate) — Minggu 5.

Rumus blueprint:
Π = C*1.00 − (C*P_kaki1 + fee1) − (C*P_kaki2 + fee2) − gas − buffer_slippage
EKSEKUSI jika Π ≥ C * min_profit_pct  (disarankan ≥ 0.8% setelah semua biaya)
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.fees import fee_kalshi, fee_polymarket, fee_limitless, GAS_POLYGON_USDC
from app.mapper.canonical import MarketInfo

DEFAULT_MIN_PROFIT_PCT = Decimal("0.008")    # 0.8%
DEFAULT_BUFFER_SLIPPAGE = Decimal("0.005")   # 0.5¢ per kontrak
DEFAULT_C_MIN = 100


@dataclass
class SignalDecision:
    execute: bool
    direction: Optional[str]     # "YES_A_NO_B" / "NO_A_YES_B"
    size: int
    gross_discount: Decimal      # 1.00 − (P1+P2) per kontrak
    total_fees: Decimal
    pi: Decimal                  # profit bersih total (dolar)
    reason: str


def _fee_for(venue: str, market: MarketInfo, P: Decimal, C: int) -> Decimal:
    if venue == "kalshi":
        return fee_kalshi(C=C, P=P, side="taker", series=market.series)
    if venue == "polymarket":
        return fee_polymarket(C=C, P=P, kategori=market.category)
    if venue == "limitless":
        return fee_limitless(C=C, P=P, side="buy", market_type="clob")
    raise ValueError(f"Venue tidak dikenal: {venue}")


def _gas_for(venue: str) -> Decimal:
    return GAS_POLYGON_USDC if venue == "polymarket" else Decimal("0")


def evaluate_pair(
    market_a: MarketInfo,
    market_b: MarketInfo,
    C: int = DEFAULT_C_MIN,
    min_profit_pct: Decimal = DEFAULT_MIN_PROFIT_PCT,
    buffer_slippage: Decimal = DEFAULT_BUFFER_SLIPPAGE,
) -> SignalDecision:
    """Coba dua arah arbitrase, pilih yang paling untung, lalu putuskan."""
    if None in (market_a.yes_price, market_a.no_price, market_b.yes_price, market_b.no_price):
        return SignalDecision(False, None, C, Decimal(0), Decimal(0), Decimal(0),
                              "Harga YES/NO belum lengkap")

    best = None
    directions = [
        ("YES_A_NO_B", market_a.yes_price, market_a, market_b.no_price, market_b),
        ("NO_A_YES_B", market_a.no_price, market_a, market_b.yes_price, market_b),
    ]

    for name, p1, m1, p2, m2 in directions:
        fee1 = _fee_for(m1.venue, m1, p1, C)
        fee2 = _fee_for(m2.venue, m2, p2, C)
        gas = _gas_for(m1.venue) + _gas_for(m2.venue)

        cost = C * p1 + fee1 + C * p2 + fee2 + gas
        pi_net = C * Decimal("1.00") - cost - (buffer_slippage * C)

        cand = SignalDecision(
            execute=False, direction=name, size=C,
            gross_discount=Decimal("1.00") - (p1 + p2),
            total_fees=fee1 + fee2 + gas, pi=pi_net, reason="",
        )
        if best is None or cand.pi > best.pi:
            best = cand

    threshold = C * min_profit_pct
    if best.pi >= threshold:
        best.execute = True
        best.reason = f"Π {best.pi:.2f} ≥ threshold {threshold:.2f} → EKSEKUSI"
    else:
        best.reason = f"Π {best.pi:.2f} < threshold {threshold:.2f} → TUNGGU"
    return best