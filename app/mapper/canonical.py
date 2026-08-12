"""
Canonical Key: identitas universal lintas venue.
Dua market dengan canonical key yang sama = market yang sama = boleh di-lock.
"""
# from dataclasses import dataclass, asdict
from dataclasses import dataclass, asdict, field
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class CanonicalKey:
    """
    Identitas unik sebuah market biner.
    
    Args:
        asset: simbol aset (BTC, ETH, FED, dll)
        template: jenis pertanyaan (UP_DOWN, ABOVE_STRIKE, YES_NO_EVENT)
        interval: periode waktu (15m, 1h, daily, 2026)
        strike: harga patokan (untuk UP_DOWN bisa None atau Decimal)
        close_ts: waktu settlement dalam epoch detik UTC
        outcome_definition: deskripsi hasil YES (untuk audit)
    """
    asset: str
    template: str
    interval: str
    strike: Optional[Decimal]
    close_ts: int  # epoch seconds UTC
    # outcome_definition: str
    outcome_definition: str = field(compare=False)  # <-- TAMBAHKAN INI     
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def __repr__(self) -> str:
        return (f"{self.asset}.{self.template}.{self.interval}"
                f"{'.' + str(self.strike) if self.strike else ''}"
                f"@{self.close_ts}")


@dataclass
class MarketInfo:
    """Informasi lengkap sebuah market di satu venue."""
    venue: str              # "polymarket" / "kalshi" / "limitless"
    venue_id: str           # ID asli di venue (ticker/condition_id)
    title: str              # Judul asli dari venue
    canonical_key: Optional[CanonicalKey]  # None = tidak bisa di-parse
    category: str           # Crypto, Politics, Sports, dll
    series: Optional[str]   # Khusus Kalshi (KXBTCY, KXFED, dll)
    is_parlay: bool         # Apakah parlay/judi gabungan?
    is_live_sport: bool     # Olahraga langsung (delay 3 detik)?
    yes_price: Optional[Decimal]
    no_price: Optional[Decimal]
    liquidity_usd: Optional[Decimal]
    settlement_source: str  # Sumber oracle/penyelesaian
    raw_data: dict          # Data mentah dari API (untuk audit)
