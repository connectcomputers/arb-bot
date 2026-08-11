"""
Pairing Engine: mencocokkan market antar venue berdasarkan canonical key.

Output: daftar LOCK (boleh di-arbitrase) dan SKIP (dibuang dengan alasan).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from app.mapper.canonical import MarketInfo, CanonicalKey
from app.mapper.skip_codes import SkipCode, EXCLUDED_CATEGORIES, EXCLUDED_TEMPLATES


@dataclass
class LockRecord:
    """Market yang berhasil di-lock (boleh di-arbitrase)."""
    key: CanonicalKey
    markets: List[MarketInfo]  # 2 atau 3 market (satu per venue)
    lock_ts: int               # Waktu di-lock
    last_validated: int        # Waktu validasi terakhir


@dataclass
class SkipRecord:
    """Market yang di-skip (tidak di-lock) dengan alasan."""
    market: MarketInfo
    skip_code: SkipCode
    reason_detail: str = ""


@dataclass
class PairingResult:
    """Hasil pairing untuk semua market yang di-scan."""
    locked: List[LockRecord] = field(default_factory=list)
    skipped: List[SkipRecord] = field(default_factory=list)
    
    @property
    def lock_count(self) -> int:
        return len(self.locked)
    
    @property
    def skip_count(self) -> int:
        return len(self.skipped)


def pair_markets(
    polymarket_markets: List[MarketInfo],
    kalshi_markets: List[MarketInfo],
    limitless_markets: Optional[List[MarketInfo]] = None,
    min_liquidity_usd: float = 100.0,
    min_ttl_seconds: int = 60,
) -> PairingResult:
    """
    Algoritma pairing:
    1. Saring market yang valid per venue
    2. Kelompokkan berdasarkan canonical key
    3. Untuk setiap canonical key, kalau muncul di ≥2 venue → LOCK
    4. Sisanya → SKIP dengan alasan
    
    Returns:
        PairingResult dengan daftar locked dan skipped
    """
    import time
    now_ts = int(time.time())
    limitless_markets = limitless_markets or []
    
    result = PairingResult()
    
    # Step 1: Validasi & saring setiap market
    valid_markets: List[MarketInfo] = []
    
    for market in polymarket_markets + kalshi_markets + limitless_markets:
        skip = _validate_market(market, now_ts, min_liquidity_usd, min_ttl_seconds)
        if skip:
            result.skipped.append(skip)
        else:
            valid_markets.append(market)
    
    # Step 2: Kelompokkan berdasarkan canonical key
    key_to_markets: Dict[CanonicalKey, List[MarketInfo]] = {}
    for market in valid_markets:
        key = market.canonical_key
        if key is None:
            continue
        key_to_markets.setdefault(key, []).append(market)
    
    # Step 3: LOCK / SKIP berdasarkan jumlah venue
    for key, markets in key_to_markets.items():
        venues = {m.venue for m in markets}
        
        if len(venues) >= 2:
            # LOCK: ada di ≥2 venue berbeda
            result.locked.append(LockRecord(
                key=key,
                markets=markets,
                lock_ts=now_ts,
                last_validated=now_ts,
            ))
        else:
            # SKIP: hanya di 1 venue
            for m in markets:
                result.skipped.append(SkipRecord(
                    market=m,
                    skip_code=SkipCode.S1,
                    reason_detail=f"Hanya ada di {m.venue}, tidak ada pasangan di venue lain",
                ))
    
    return result


def _validate_market(
    market: MarketInfo,
    now_ts: int,
    min_liquidity_usd: float,
    min_ttl_seconds: int,
) -> Optional[SkipRecord]:
    """
    Validasi sebuah market. Kembalikan SkipRecord jika gagal, None jika valid.
    """
    # Check S8: halted/delisted
    if market.raw_data.get("status") in ("halted", "delisted", "closed"):
        return SkipRecord(market, SkipCode.S8, f"Status: {market.raw_data.get('status')}")
    
    # Check S9: parlay/non-biner
    if market.is_parlay:
        return SkipRecord(market, SkipCode.S9, f"Parlay/non-biner: {market.title[:50]}")
    
    # Check S5: live sport (delay 3 detik)
    if market.is_live_sport:
        return SkipRecord(market, SkipCode.S5, f"Olahraga langsung: {market.title[:50]}")
    
    # Check S11: kategori dikecualikan
    if market.category in EXCLUDED_CATEGORIES:
        return SkipRecord(market, SkipCode.S11, f"Kategori: {market.category}")
    
    # Check S10: tidak bisa di-parse
    if market.canonical_key is None:
        return SkipRecord(market, SkipCode.S10, f"Judul tidak dikenali: {market.title[:50]}")
    
    # Check template yang dikecualikan
    if market.canonical_key.template in EXCLUDED_TEMPLATES:
        return SkipRecord(market, SkipCode.S9, f"Template dikecualikan: {market.canonical_key.template}")
    
    # Check S7: TTL terlalu pendek
    ttl = market.canonical_key.close_ts - now_ts
    if ttl < min_ttl_seconds:
        return SkipRecord(market, SkipCode.S7, f"TTL {ttl}s < {min_ttl_seconds}s minimum")
    
    # Check S6: likuiditas rendah (bila ada data)
    if market.liquidity_usd is not None and market.liquidity_usd < min_liquidity_usd:
        return SkipRecord(market, SkipCode.S6, f"Likuiditas ${market.liquidity_usd:.0f} < ${min_liquidity_usd:.0f}")
    
    return None