"""
Executor Base — interface bersama untuk semua venue.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderOutcome(str, Enum):
    YES = "yes"
    NO = "no"


class OrderType(str, Enum):
    """Tipe order (time-in-force)."""
    IOC = "IOC"          # Immediate-or-Cancel (wajib fill sekarang)
    FOK = "FOK"          # Fill-or-Kill (wajib full fill atau tolak)
    GTC = "GTC"          # Good-Till-Cancelled (limit order)
    GTT = "GTT"          # Good-Till-Time (dengan expiry)


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class OrderRequest:
    """Request order ke executor."""
    venue: str                     # "kalshi" / "polymarket" / "limitless"
    market_id: str                 # ticker / condition_id / market_id
    side: OrderSide
    outcome: OrderOutcome          # YES / NO
    price: Decimal                 # harga max (buy) atau min (sell)
    size: int                      # jumlah kontrak
    order_type: OrderType = OrderType.FOK
    worst_price: Optional[Decimal] = None   # batas harga terburuk yang diterima
    expiry_ts: Optional[int] = None         # untuk GTT
    idempotency_key: Optional[str] = None   # mencegah double-submit


@dataclass
class OrderResult:
    """Hasil dari submit_order."""
    order_id: str
    status: OrderStatus
    filled_size: int = 0
    filled_price: Optional[Decimal] = None
    timestamp: int = 0
    raw_response: dict = field(default_factory=dict)
    error_message: Optional[str] = None

    @property
    def is_final(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.REJECTED,
                               OrderStatus.CANCELLED, OrderStatus.TIMEOUT)

    @property
    def is_success(self) -> bool:
        return self.status == OrderStatus.FILLED


class Executor(ABC):
    """Interface bersama — semua executor harus implementasikan ini."""

    def __init__(self, live: bool = False):
        self.live = live
        self.venue_name: str = "base"

    @abstractmethod
    async def submit_order(self, request: OrderRequest) -> OrderResult:
        """Kirim order. Return OrderResult dengan status final."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Batalkan order pending. Return True kalau berhasil."""
        ...

    @abstractmethod
    async def get_balance(self) -> dict:
        """Return {"available": Decimal, "venue": str}."""
        ...