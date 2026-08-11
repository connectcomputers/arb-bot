"""
Normalizer: mengubah judul market mentah dari venue → CanonicalKey.

Mulai dari crypto (paling deterministik). Kategori lain akan ditambah bertahap.
"""
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

from app.mapper.canonical import CanonicalKey, MarketInfo
from app.mapper.skip_codes import SkipCode


# ==========================
# POLYMARKET NORMALIZER
# ==========================
def normalize_polymarket(raw_market: dict) -> MarketInfo:
    """
    Parse market dari Polymarket API response.
    
    Contoh judul yang bisa di-parse:
    - "Bitcoin Up or Down 15 minutes" (template UP_DOWN)
    - "Bitcoin above $65,000 end of day" (template ABOVE_STRIKE)
    """
    title = raw_market.get("question", "")
    category = raw_market.get("category", "Other")
    condition_id = raw_market.get("conditionId", "")
    end_date_iso = raw_market.get("endDate", "")
    
    # Parse waktu settlement
    close_ts = None
    if end_date_iso:
        try:
            dt = datetime.fromisoformat(end_date_iso.replace("Z", "+00:00"))
            close_ts = int(dt.timestamp())
        except (ValueError, AttributeError):
            pass
    
    # Attempt parse crypto 15-min
    key = None
    crypto_15m = _parse_poly_crypto_15m(title, close_ts)
    if crypto_15m:
        key = crypto_15m
    
    # Attempt parse crypto daily above strike
    if not key:
        crypto_above = _parse_poly_crypto_above(title, close_ts)
        if crypto_above:
            key = crypto_above
    
    return MarketInfo(
        venue="polymarket",
        venue_id=condition_id,
        title=title,
        canonical_key=key,
        category=category,
        series=None,
        is_parlay=False,  # Polymarket tidak punya parlay native
        is_live_sport=(category == "Sports"),
        yes_price=None,  # Akan diisi dari orderbook terpisah
        no_price=None,
        liquidity_usd=None,
        settlement_source="UMA Oracle",
        raw_data=raw_market,
    )


def _parse_poly_crypto_15m(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse 'Bitcoin Up or Down 15 minutes' dan sejenisnya."""
    title_lower = title.lower()
    
    # Regex untuk crypto up/down
    match = re.match(
        r"^(bitcoin|btc|ethereum|eth)\s+(up\s+or\s+down|up|down)\s+(\d+)\s*(m|min|minute|h|hour)",
        title_lower,
        re.IGNORECASE
    )
    if not match:
        return None
    
    asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
    asset = asset_map[match.group(1).lower()]
    interval_raw = match.group(3) + match.group(4)[:1]  # "15m", "1h"
    interval = interval_raw.lower()
    
    if close_ts is None:
        return None
    
    return CanonicalKey(
        asset=asset,
        template="UP_DOWN",
        interval=interval,
        strike=None,
        close_ts=close_ts,
        outcome_definition=f"{asset} price {'higher' if 'up' in title_lower else 'lower'} than {interval} ago",
    )


def _parse_poly_crypto_above(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse 'Bitcoin above $65,000 end of day'."""
    title_lower = title.lower()
    
    match = re.match(
        r"^(bitcoin|btc|ethereum|eth)\s+(above|below)\s+\$?([\d,]+(?:\.\d+)?)\s*(?:end\s+of\s+day|daily|by\s+\d{4}|\w+)",
        title_lower,
        re.IGNORECASE
    )
    if not match:
        return None
    
    asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
    asset = asset_map[match.group(1).lower()]
    strike_str = match.group(3).replace(",", "")
    strike = Decimal(strike_str)
    
    if close_ts is None:
        return None
    
    direction = "ABOVE" if match.group(2).lower() == "above" else "BELOW"
    
    return CanonicalKey(
        asset=asset,
        template=direction + "_STRIKE",
        interval="daily",
        strike=strike,
        close_ts=close_ts,
        outcome_definition=f"{asset} price {match.group(2).lower()} ${strike} at close",
    )


# ==========================
# KALSHI NORMALIZER
# ==========================
def normalize_kalshi(raw_market: dict) -> MarketInfo:
    """
    Parse market dari Kalshi API response.
    
    Contoh judul yang bisa di-parse:
    - "Bitcoin Up or Down 15 minutes" (series KXBTC, template UP_DOWN)
    - "Bitcoin above $65,000 on August 8" (template ABOVE_STRIKE)
    
    Juga deteksi PARLAY dari kata kunci 'yes X, yes Y, yes Z'.
    """
    title = raw_market.get("title", "")
    ticker = raw_market.get("ticker", "")
    event_ticker = raw_market.get("event_ticker", "")
    close_time = raw_market.get("close_time", "")
    
    # Parse waktu settlement
    close_ts = None
    if close_time:
        try:
            dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            close_ts = int(dt.timestamp())
        except (ValueError, AttributeError):
            pass
    
    # Deteksi parlay (ciri khas: judul berisi banyak 'yes')
    is_parlay = _detect_kalshi_parlay(title)
    
    # Deteksi series
    series = _extract_kalshi_series(event_ticker, ticker)
    
    # Attempt parse
    key = None
    if not is_parlay:
        crypto_15m = _parse_kalshi_crypto_15m(title, close_ts)
        if crypto_15m:
            key = crypto_15m
    
    return MarketInfo(
        venue="kalshi",
        venue_id=ticker,
        title=title,
        canonical_key=key,
        category=_kalshi_infer_category(title, event_ticker),
        series=series,
        is_parlay=is_parlay,
        is_live_sport=False,  # Kalshi tidak punya live sport
        yes_price=None,
        no_price=None,
        liquidity_usd=None,
        settlement_source="Kalshi Official",
        raw_data=raw_market,
    )


def _detect_kalshi_parlay(title: str) -> bool:
    """Deteksi judul parlay: 'yes X, yes Y, yes Z...'."""
    # Ciri khas: judul diawali 'yes' dan ada banyak 'yes' lain
    title_lower = title.lower()
    yes_count = title_lower.count("yes ")
    return yes_count >= 2 or title_lower.startswith("yes ") and "," in title_lower


def _extract_kalshi_series(event_ticker: str, ticker: str) -> Optional[str]:
    """Ekstrak series dari ticker Kalshi (misal: KXBTCY-25DEC31-T75K → KXBTCY)."""
    base = event_ticker or ticker
    match = re.match(r"^(KX[A-Z]+)", base, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _parse_kalshi_crypto_15m(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse judul crypto 15-min Kalshi."""
    title_lower = title.lower()
    
    match = re.match(
        r"^(bitcoin|btc|ethereum|eth)\s+(up\s+or\s+down|up|down)\s+(\d+)\s*(m|min|minute|h|hour)",
        title_lower,
        re.IGNORECASE
    )
    if not match:
        return None
    
    asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
    asset = asset_map[match.group(1).lower()]
    interval = match.group(3) + match.group(4)[:1]
    interval = interval.lower()
    
    if close_ts is None:
        return None
    
    return CanonicalKey(
        asset=asset,
        template="UP_DOWN",
        interval=interval,
        strike=None,
        close_ts=close_ts,
        outcome_definition=f"{asset} price {'higher' if 'up' in title_lower else 'lower'} than {interval} ago",
    )


def _kalshi_infer_category(title: str, event_ticker: str) -> str:
    """Infer kategori dari judul Kalshi."""
    title_lower = (title + " " + event_ticker).lower()
    if any(k in title_lower for k in ["bitcoin", "btc", "ethereum", "eth", "kxbtc", "kxeth"]):
        return "Crypto"
    if any(k in title_lower for k in ["fed", "kxfed", "cpi", "kxcpi", "gdp", "kxgdp"]):
        return "Economics"
    if any(k in title_lower for k in ["trump", "biden", "harris", "election", "kxel"]):
        return "Politics"
    return "Other"


# ==========================
# LIMITLESS NORMALIZER (Placeholder)
# ==========================
def normalize_limitless(raw_market: dict) -> MarketInfo:
    """
    Normalizer Limitless. Saat ini placeholder — akan dilengkapi saat kita
    punya sampel data asli dari API Limitless.
    
    Limitless hampir 100% crypto (BTC/ETH per jam/hari), jadi template-nya
    akan fokus pada crypto up/down dan above-strike.
    """
    title = raw_market.get("title", raw_market.get("question", ""))
    market_id = raw_market.get("id", raw_market.get("marketId", ""))
    
    return MarketInfo(
        venue="limitless",
        venue_id=market_id,
        title=title,
        canonical_key=None,  # Placeholder
        category="Crypto",
        series=None,
        is_parlay=False,
        is_live_sport=False,
        yes_price=None,
        no_price=None,
        liquidity_usd=None,
        settlement_source="Limitless Official",
        raw_data=raw_market,
    )