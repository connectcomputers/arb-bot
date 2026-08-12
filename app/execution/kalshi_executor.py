"""
Kalshi Executor — Mode Simulasi + interface production-ready.

Di mode live (nanti):
- Auth via API Key + Secret (HMAC-SHA256 di header Authorization)
- POST ke /trade-api/v2/portfolio/orders
- Harga dalam cents (integer), size dalam kontrak
"""
import os
import time
import uuid
from decimal import Decimal

import httpx

from app.execution.base import (
    Executor, OrderRequest, OrderResult, OrderStatus, OrderSide, OrderOutcome
)

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"


class KalshiExecutor(Executor):
    def __init__(self, live: bool = False, api_key: str = "", api_secret: str = ""):
        super().__init__(live=live)
        self.venue_name = "kalshi"
        self.api_key = api_key or os.getenv("KALSHI_API_KEY", "")
        self.api_secret = api_secret or os.getenv("KALSHI_API_SECRET", "")
        self._simulated_fills = {}  # untuk mode simulasi

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit order ke Kalshi."""
        # Validasi dasar
        if request.venue != "kalshi":
            return OrderResult(
                order_id="", status=OrderStatus.REJECTED,
                error_message=f"Venue mismatch: expected kalshi, got {request.venue}",
                timestamp=int(time.time()),
            )

        if not self.live:
            return await self._simulate_fill(request)

        # === MODE LIVE (akan aktif di Tahap 12) ===
        return await self._submit_live(request)

    async def _simulate_fill(self, request: OrderRequest) -> OrderResult:
        """Simulasi fill: asumsikan order ter-fill penuh di worst_price."""
        order_id = f"KALSHI-SIM-{uuid.uuid4().hex[:8].upper()}"

        # Simulasi: FOK fill penuh di harga request
        filled_price = request.worst_price if request.worst_price else request.price

        result = OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            filled_size=request.size,
            filled_price=filled_price,
            timestamp=int(time.time()),
            raw_response={"simulated": True, "request": {
                "market_id": request.market_id,
                "side": request.side.value,
                "outcome": request.outcome.value,
                "price": str(request.price),
                "size": request.size,
            }},
        )
        self._simulated_fills[order_id] = result
        return result

    async def _submit_live(self, request: OrderRequest) -> OrderResult:
        """Submit order ke Kalshi API asli (placeholder untuk Tahap 12)."""
        if not self.api_key or not self.api_secret:
            return OrderResult(
                order_id="", status=OrderStatus.REJECTED,
                error_message="KALSHI_API_KEY atau KALSHI_API_SECRET kosong",
                timestamp=int(time.time()),
            )

        # TODO Tahap 12: implementasi HMAC signature + actual POST
        # Payload Kalshi: {"ticker": ..., "action": "buy"|"sell", "side": "yes"|"no",
        #                  "count": size, "type": "market"|"limit",
        #                  "buy_price": cents, "sell_price": cents}
        return OrderResult(
            order_id="", status=OrderStatus.REJECTED,
            error_message="Live mode belum diimplementasikan (Tahap 12)",
            timestamp=int(time.time()),
        )

    async def cancel_order(self, order_id: str) -> bool:
        if not self.live:
            return order_id in self._simulated_fills
        # TODO Tahap 12: DELETE /portfolio/orders/{id}
        return False

    async def get_balance(self) -> dict:
        if not self.live:
            return {"venue": "kalshi", "available": Decimal("10000.00"),
                    "simulated": True}
        # TODO Tahap 12: GET /portfolio/balance
        return {"venue": "kalshi", "available": Decimal("0")}