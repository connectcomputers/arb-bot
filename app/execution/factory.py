"""
Factory function untuk instantiasi executor berdasarkan venue.
"""
from app.execution.base import Executor
from app.execution.kalshi_executor import KalshiExecutor
from app.execution.polymarket_executor import PolymarketExecutor
from app.execution.limitless_executor import LimitlessExecutor


def get_executor(venue: str, live: bool = False) -> Executor:
    """Return executor yang sesuai untuk venue."""
    venue = venue.lower()
    if venue == "kalshi":
        return KalshiExecutor(live=live)
    elif venue == "polymarket":
        return PolymarketExecutor(live=live)
    elif venue == "limitless":
        return LimitlessExecutor(live=live)
    else:
        raise ValueError(f"Venue tidak dikenal: {venue}")