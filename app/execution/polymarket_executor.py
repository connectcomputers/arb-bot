"""
Polymarket Executor — Mode Simulasi + interface EIP-712 signing.

Mode live nanti:
- Auth via Polygon wallet (EIP-712 signature)
- POST ke https://clob.polymarket.com/order
- Proxy wallet per user (Py-Tokens)
"""
import os
import time
import uuid
from decimal import Decimal

from app.execution.base import (
    Executor, OrderRequest, OrderResult, OrderStatus, OrderSide, OrderOutcome
)


class PolymarketExecutor(Executor):
    def __init__(self, live: bool = False, private_key: str = ""):
        super().__init__(live=live)
        self.venue_name = "polymarket"
        self.private_key = private_key or os.getenv("POLYMARKET_PRIVATE_KEY", "")
        self._simulated_fills = {}

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        if request.venue != "polymarket":
            return OrderResult(
                order_id="", status=OrderStatus.REJECTED,
                error_message=f"Venue mismatch: expected polymarket, got {request.venue}",
                timestamp=int(time.time()),
            )

        if not self.live:
            return await self._simulate_fill(request)

        return await self._submit_live(request)

    async def _simulate_fill(self, request: OrderRequest) -> OrderResult:
        order_id = f"POLY-SIM-{uuid.uuid4().hex[:8].upper()}"
        filled_price = request.worst_price if request.worst_price else request.price

        result = OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            filled_size=request.size,
            filled_price=filled_price,
            timestamp=int(time.time()),
            raw_response={"simulated": True},
        )
        self._simulated_fills[order_id] = result
        return result

    async def _submit_live(self, request: OrderRequest) -> OrderResult:
        if not self.private_key:
            return OrderResult(
                order_id="", status=OrderStatus.REJECTED,
                error_message="POLYMARKET_PRIVATE_KEY kosong",
                timestamp=int(time.time()),
            )
        # TODO Tahap 12: implement EIP-712 signing via py-clob-client
        return OrderResult(
            order_id="", status=OrderStatus.REJECTED,
            error_message="Live mode belum diimplementasikan (Tahap 12)",
            timestamp=int(time.time()),
        )

    async def cancel_order(self, order_id: str) -> bool:
        if not self.live:
            return order_id in self._simulated_fills
        return False

    async def get_balance(self) -> dict:
        if not self.live:
            return {"venue": "polymarket", "available": Decimal("10000.00"),
                    "simulated": True}
        return {"venue": "polymarket", "available": Decimal("0")}