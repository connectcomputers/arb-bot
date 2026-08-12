"""
Limitless Executor — Mode Simulasi + interface API bearer.

Mode live nanti:
- Auth via API Key (header Authorization: Bearer ...)
- POST ke https://api.limitless.com/v1/orders
"""
import os
import time
import uuid
from decimal import Decimal

from app.execution.base import (
    Executor, OrderRequest, OrderResult, OrderStatus, OrderSide, OrderOutcome
)


class LimitlessExecutor(Executor):
    def __init__(self, live: bool = False, api_key: str = ""):
        super().__init__(live=live)
        self.venue_name = "limitless"
        self.api_key = api_key or os.getenv("LIMITLESS_API_KEY", "")
        self._simulated_fills = {}

    async def submit_order(self, request: OrderRequest) -> OrderResult:
        if request.venue != "limitless":
            return OrderResult(
                order_id="", status=OrderStatus.REJECTED,
                error_message=f"Venue mismatch: expected limitless, got {request.venue}",
                timestamp=int(time.time()),
            )

        if not self.live:
            return await self._simulate_fill(request)

        return await self._submit_live(request)

    async def _simulate_fill(self, request: OrderRequest) -> OrderResult:
        order_id = f"LMT-SIM-{uuid.uuid4().hex[:8].upper()}"
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
        if not self.api_key:
            return OrderResult(
                order_id="", status=OrderStatus.REJECTED,
                error_message="LIMITLESS_API_KEY kosong",
                timestamp=int(time.time()),
            )
        # TODO Tahap 12: implement Bearer auth + POST
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
            return {"venue": "limitless", "available": Decimal("10000.00"),
                    "simulated": True}
        return {"venue": "limitless", "available": Decimal("0")}