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

    # TAMBAHKAN INI: Attempt parse economics
    if not key:
        econ = _parse_poly_economics(title, close_ts)
        if econ:
            key = econ

    # TAMBAHKAN BARIS INI: Attempt parse politics
    if not key:
        politics = _parse_poly_politics(title, close_ts)
        if politics:
            key = politics

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

def _parse_poly_economics(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse judul economics Polymarket (Fed, CPI, GDP, dll)."""
    title_lower = title.lower()
    
    asset = None
    if "fed" in title_lower or "fomc" in title_lower or "rate cut" in title_lower:
        asset = "FED_RATE"
    elif "cpi" in title_lower or "inflation" in title_lower:
        asset = "CPI"
    elif "gdp" in title_lower:
        asset = "GDP"
    elif "payroll" in title_lower or "nonfarm" in title_lower or "jobs" in title_lower:
        asset = "NONFARM_PAYROLLS"
    elif "unemployment" in title_lower:
        asset = "UNEMPLOYMENT_U3"
        
    if not asset:
        return None
        
    # Ekstrak tahun dari judul
    year_match = re.search(r'\b(20\d{2})\b', title)
    year = year_match.group(1) if year_match else None
    
    # Ekstrak bulan jika ada
    month_match = re.search(
        r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\b',
        title_lower
    )
    month_str = month_match.group(1)[:3] if month_match else None
    
    if close_ts is None and year:
        try:
            dt = datetime(int(year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            close_ts = int(dt.timestamp())
        except ValueError:
            return None
            
    if close_ts is None:
        return None
        
    interval = f"{month_str}-{year}" if month_str and year else f"year-{year}" if year else "open"
    
    return CanonicalKey(
        asset=asset,
        template="YES_NO_EVENT",
        interval=interval,
        strike=None,
        close_ts=close_ts,
        outcome_definition=f"Event: {title}",
    )

# def _parse_poly_politics(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
#     """
#     Parse judul politics Polymarket.
    
#     Contoh yang bisa di-parse:
#     - "Will Trump win the 2028 presidential election?"
#     - "CLARITY Act signed into law in 2026?"
#     - "Will [X] happen by [Y]?"
#     """
#     title_lower = title.lower()
    
#     # Pola: "Will [subject] [verb] by [time]?"
#     match = re.match(
#         r"^will\s+(.+?)\s+(win|be|sign|pass|happen|get|become|lose|defeat)\s+(.+?)(?:\s+by\s+|\s+in\s+|\s+on\s+)?(\d{4})?",
#         title_lower,
#         re.IGNORECASE
#     )
#     if not match:
#         # Coba pola lebih umum: "[subject] [verb] in [year]?"
#         match = re.match(
#             r"^(.+?)\s+(signed|passed|enacted|ratified|happened)\s+.*?(\d{4})\??$",
#             title_lower,
#             re.IGNORECASE
#         )
#         if not match:
#             return None
#         subject = match.group(1).strip()
#         year = match.group(3)
#         template = "YES_NO_EVENT"
#     else:
#         subject = match.group(1).strip()
#         year = match.group(4) if match.group(4) else None
#         template = "YES_NO_EVENT"
    
#     # Normalisasi subject
#     asset = _normalize_politics_subject(subject)
    
#     if close_ts is None and year:
#         # Asumsi akhir tahun
#         try:
#             dt = datetime(int(year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
#             close_ts = int(dt.timestamp())
#         except ValueError:
#             return None
    
#     if close_ts is None:
#         return None
    
#     return CanonicalKey(
#         asset=asset,
#         template=template,
#         interval=f"year-{year}" if year else "open",
#         strike=None,
#         close_ts=close_ts,
#         outcome_definition=f"Event: {title}",
#     )

def _parse_poly_politics(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse judul politics Polymarket dengan logika terunifikasi."""
    title_lower = title.lower()
    
    politics_keywords = ["trump", "harris", "biden", "presidential", "election", "clarity act", "genius act", "senate", "congress"]
    if not any(kw in title_lower for kw in politics_keywords):
        return None
        
    # Penamaan asset disamakan dengan Kalshi
    asset = None
    if "presidential" in title_lower and "2028" in title_lower:
        asset = "US_PRES_2028"
    elif "presidential" in title_lower and "2024" in title_lower:
        asset = "US_PRES_2024"
    elif "clarity" in title_lower and "act" in title_lower:
        asset = "CLARITY_ACT"
    elif "trump" in title_lower:
        asset = "TRUMP"
    elif "harris" in title_lower:
        asset = "HARRIS"
    elif "biden" in title_lower:
        asset = "BIDEN"
    else:
        return None
        
    # Ekstrak tahun pakai re.search agar tidak gagal di kalimat panjang
    year_match = re.search(r'\b(20\d{2})\b', title)
    year = year_match.group(1) if year_match else None
    
    if close_ts is None and year:
        try:
            dt = datetime(int(year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            close_ts = int(dt.timestamp())
        except ValueError:
            return None
            
    if close_ts is None:
        return None
        
    interval = f"year-{year}" if year else "open"
    
    return CanonicalKey(
        asset=asset,
        template="YES_NO_EVENT",
        interval=interval,
        strike=None,
        close_ts=close_ts,
        outcome_definition=f"Event: {title}",
    )

def _normalize_politics_subject(subject: str) -> str:
    """Normalisasi nama subject politics jadi asset key konsisten."""
    subject_lower = subject.lower()
    
    # Tokoh politik
    if "trump" in subject_lower:
        return "TRUMP"
    if "harris" in subject_lower:
        return "HARRIS"
    if "biden" in subject_lower:
        return "BIDEN"
    if "desantis" in subject_lower:
        return "DESANTIS"
    if "newsom" in subject_lower:
        return "NEWSOM"
    
    # UU/Act
    if "clarity" in subject_lower and "act" in subject_lower:
        return "CLARITY_ACT"
    if "genius" in subject_lower and "act" in subject_lower:
        return "GENIUS_ACT"
    if "stablecoin" in subject_lower:
        return "STABLECOIN_BILL"
    
    # Event
    if "presidential" in subject_lower and "2028" in subject_lower:
        return "US_PRES_2028"
    if "presidential" in subject_lower and "2024" in subject_lower:
        return "US_PRES_2024"
    if "senate" in subject_lower:
        return "US_SENATE"
    
    # Fallback: slug dari subject
    return re.sub(r'[^a-z0-9]+', '_', subject_lower)[:30].upper()

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
    # is_parlay = _detect_kalshi_parlay(title)
    is_parlay = _detect_kalshi_parlay(title, event_ticker)    
    
    # Deteksi series
    series = _extract_kalshi_series(event_ticker, ticker)
    
    # Attempt parse
    # key = None
    # if not is_parlay:
    #     crypto_15m = _parse_kalshi_crypto_15m(title, close_ts)
    #     if crypto_15m:
    #         key = crypto_15m

    # Attempt parse (skip parlay)
    key = None
    if not is_parlay:
        # Coba crypto 15-min
        crypto_15m = _parse_kalshi_crypto_15m(title, close_ts)
        if crypto_15m:
            key = crypto_15m
        
        # TAMBAHKAN: Coba crypto hourly
        if not key:
            crypto_hourly = _parse_kalshi_crypto_hourly(title, close_ts)
            if crypto_hourly:
                key = crypto_hourly
        
        # TAMBAHKAN: Coba crypto daily above/below strike
        if not key:
            crypto_above = _parse_kalshi_crypto_above_strike(title, close_ts)
            if crypto_above:
                key = crypto_above
        
        # Coba economics
        if not key:
            econ = _parse_kalshi_economics(title, close_ts, event_ticker)
            if econ:
                key = econ
        
        # Coba politics
        if not key:
            politics = _parse_kalshi_politics(title, close_ts, event_ticker)
            if politics:
                key = politics

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

# Tambahkan fungsi-fungsi baru (awal)
# def _parse_kalshi_politics(title: str, close_ts: Optional[int], event_ticker: str) -> Optional[CanonicalKey]:
#     """
#     Parse judul politics Kalshi.
    
#     Contoh yang bisa di-parse:
#     - "Will Trump win 2028 presidential election?"
#     - "CLARITY Act signed into law in 2026?"
#     - Series KXEL, KXELECT, KXTRUMP, KXCLARITY, dll
#     """
#     title_lower = title.lower()
#     event_lower = (event_ticker or "").lower()
    
#     # Cek series-based politics
#     politics_series = [
#         ("kxel", "US_ELECTION"),
#         ("kxelect", "US_ELECTION"),
#         ("kxtrump", "TRUMP"),
#         ("kxharris", "HARRIS"),
#         ("kxbiden", "BIDEN"),
#         ("kxclarity", "CLARITY_ACT"),
#         ("kxgenius", "GENIUS_ACT"),
#     ]
    
#     asset = None
#     for prefix, default_asset in politics_series:
#         if event_lower.startswith(prefix):
#             asset = default_asset
#             break
    
#     if not asset:
#         # Fallback: parse judul
#         asset = _normalize_politics_subject(title)
    
#     # Ekstrak tahun dari judul
#     year_match = re.search(r'\b(20\d{2})\b', title)
#     year = year_match.group(1) if year_match else None
    
#     if close_ts is None and year:
#         try:
#             dt = datetime(int(year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
#             close_ts = int(dt.timestamp())
#         except ValueError:
#             return None
    
#     if close_ts is None:
#         return None
    
#     return CanonicalKey(
#         asset=asset,
#         template="YES_NO_EVENT",
#         interval=f"year-{year}" if year else "open",
#         strike=None,
#         close_ts=close_ts,
#         outcome_definition=f"Event: {title}",
#     )

def _parse_kalshi_politics(title: str, close_ts: Optional[int], event_ticker: str) -> Optional[CanonicalKey]:
    """Parse judul politics Kalshi dengan logika terunifikasi."""
    title_lower = title.lower()
    event_lower = (event_ticker or "").lower()
    
    politics_series = ["kxel", "kxelect", "kxtrump", "kxharris", "kxbiden", "kxclarity", "kxgenius"]
    is_politics_series = any(event_lower.startswith(prefix) for prefix in politics_series)
    
    politics_keywords = ["trump", "harris", "biden", "presidential", "election", "clarity act", "genius act", "senate", "congress"]
    has_politics_keyword = any(kw in title_lower for kw in politics_keywords)
    
    if not (is_politics_series or has_politics_keyword):
        return None
        
    # Penamaan asset disamakan dengan Polymarket
    asset = None
    if "presidential" in title_lower and "2028" in title_lower:
        asset = "US_PRES_2028"
    elif "presidential" in title_lower and "2024" in title_lower:
        asset = "US_PRES_2024"
    elif "clarity" in title_lower and "act" in title_lower:
        asset = "CLARITY_ACT"
    elif "trump" in title_lower:
        asset = "TRUMP"
    elif "harris" in title_lower:
        asset = "HARRIS"
    elif "biden" in title_lower:
        asset = "BIDEN"
    else:
        if is_politics_series:
            asset = "US_ELECTION"
        else:
            return None
            
    year_match = re.search(r'\b(20\d{2})\b', title)
    if not year_match:
        # Fallback: ekstrak tahun dari event_ticker (misal KXEL-28TRUMP -> 2028)
        year_ticker_match = re.search(r'-(2\d)([A-Z]{3})', event_ticker, re.IGNORECASE)
        if year_ticker_match:
            year = "20" + year_ticker_match.group(1)
        else:
            year = None
    else:
        year = year_match.group(1)
        
    if close_ts is None and year:
        try:
            dt = datetime(int(year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            close_ts = int(dt.timestamp())
        except ValueError:
            return None
            
    if close_ts is None:
        return None
        
    interval = f"year-{year}" if year else "open"
    
    return CanonicalKey(
        asset=asset,
        template="YES_NO_EVENT",
        interval=interval,
        strike=None,
        close_ts=close_ts,
        outcome_definition=f"Event: {title}",
    )

def _parse_kalshi_economics(title: str, close_ts: Optional[int], event_ticker: str) -> Optional[CanonicalKey]:
    """
    Parse judul economics Kalshi.
    
    Contoh yang bisa di-parse:
    - "Fed rate cut in September 2026?"
    - "CPI for August 2026 above 3%?"
    - "GDP Q3 2026 above 2%?"
    
    Series: KXFED, KXCPI, KXGDP, KXPAYROLLS, KXU3, KXRATECUTCOUNT
    """
    title_lower = title.lower()
    event_lower = (event_ticker or "").lower()
    
    # Mapping series ke asset
    econ_series = {
        "kxfed": "FED_RATE",
        "kxratecutcount": "FED_CUTS",
        "kxcpi": "CPI",
        "kxgdp": "GDP",
        "kxpayrolls": "NONFARM_PAYROLLS",
        "kxu3": "UNEMPLOYMENT_U3",
    }
    
    asset = None
    for prefix, default_asset in econ_series.items():
        if event_lower.startswith(prefix):
            asset = default_asset
            break
    
    if not asset:
        # Fallback: parse judul
        if "fed" in title_lower or "fomc" in title_lower:
            asset = "FED_RATE"
        elif "cpi" in title_lower:
            asset = "CPI"
        elif "gdp" in title_lower:
            asset = "GDP"
        elif "payroll" in title_lower or "nonfarm" in title_lower:
            asset = "NONFARM_PAYROLLS"
        elif "unemployment" in title_lower:
            asset = "UNEMPLOYMENT_U3"
        else:
            return None
    
    # Ekstrak tahun
    year_match = re.search(r'\b(20\d{2})\b', title)
    year = year_match.group(1) if year_match else None
    
    # Ekstrak bulan kalau ada
    month_match = re.search(
        r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\b',
        title_lower
    )
    month_str = month_match.group(1)[:3] if month_match else None
    
    if close_ts is None and year:
        try:
            dt = datetime(int(year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            close_ts = int(dt.timestamp())
        except ValueError:
            return None
    
    if close_ts is None:
        return None
    
    interval = f"{month_str}-{year}" if month_str and year else f"year-{year}" if year else "open"
    
    return CanonicalKey(
        asset=asset,
        template="YES_NO_EVENT",
        interval=interval,
        strike=None,
        close_ts=close_ts,
        outcome_definition=f"Event: {title}",
    )
# Tambahkan fungsi-fungsi baru (akhir)

# def _detect_kalshi_parlay(title: str) -> bool:
#     """Deteksi judul parlay: 'yes X, yes Y, yes Z...'."""
#     # Ciri khas: judul diawali 'yes' dan ada banyak 'yes' lain
#     title_lower = title.lower()
#     yes_count = title_lower.count("yes ")
#     return yes_count >= 2 or title_lower.startswith("yes ") and "," in title_lower

def _detect_kalshi_parlay(title: str, event_ticker: str = "") -> bool:
    """
    Deteksi parlay Kalshi secara CERDAS (tidak false positive).
    
    Parlay asli Kalshi punya ciri:
    - Event ticker berawalan 'PARLAY-' atau 'PAR-'
    - Judul berisi ≥3 'yes' DAN ada koma (pola 'yes X, yes Y, yes Z')
    - Atau judul diawali 'Parlay:' atau 'Build Your Parlay'
    
    Market biner biasa mungkin punya 'yes' di judul tapi tidak pola di atas.
    """
    title_lower = title.lower()
    event_lower = (event_ticker or "").lower()
    
    # Ciri paling kuat: ticker event diawali PARLAY- atau PAR-
    if event_lower.startswith(("parlay-", "par-")):
        return True
    
    # Ciri kuat: judul diawali 'parlay:' atau 'build your parlay'
    if title_lower.startswith(("parlay:", "parlay -", "build your parlay", "create parlay")):
        return True
    
    # Ciri struktural: ≥3 'yes' DAN ada koma (pola 'yes X, yes Y, yes Z')
    # Tapi pastikan 'yes' bukan bagian kata lain ('yesterday', 'yes/no')
    import re
    yes_matches = re.findall(r'\byes\b', title_lower)
    has_yes_pattern = len(yes_matches) >= 3 and ',' in title
    
    return has_yes_pattern

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

# def _parse_kalshi_crypto_above_strike(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
#     """
#     Parse judul crypto daily Kalshi: 'Will Bitcoin be above $70,000 on August 12?'
#     """
#     title_lower = title.lower()
    
#     match = re.match(
#         r"^(bitcoin|btc|ethereum|eth)\s+(above|below)\s+\$?([\d,]+(?:\.\d+)?)\s*(?:on|by|end of)?",
#         title_lower,
#         re.IGNORECASE
#     )
#     if not match:
#         return None
    
#     asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
#     asset = asset_map[match.group(1).lower()]
#     direction = "ABOVE" if match.group(2).lower() == "above" else "BELOW"
#     strike_str = match.group(3).replace(",", "")
#     strike = Decimal(strike_str)
    
#     if close_ts is None:
#         return None
    
#     return CanonicalKey(
#         asset=asset,
#         template=direction + "_STRIKE",
#         interval="daily",
#         strike=strike,
#         close_ts=close_ts,
#         outcome_definition=f"{asset} price {match.group(2).lower()} ${strike} at close",
#     )

def _parse_kalshi_crypto_above_strike(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """
    Parse judul crypto daily Kalshi (fleksibel):
    - 'Will Bitcoin be above $70,000 on August 12?'
    - 'Bitcoin above $65,000 on August 8'
    """
    title_lower = title.lower()
    
    # re.search (bukan re.match) + 'be' opsional
    match = re.search(
        r"(bitcoin|btc|ethereum|eth)\s+(?:be\s+)?(above|below)\s+\$?([\d,]+(?:\.\d+)?)",
        title_lower,
    )
    if not match:
        return None
    
    asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
    asset = asset_map[match.group(1).lower()]
    direction = "ABOVE" if match.group(2).lower() == "above" else "BELOW"
    strike = Decimal(match.group(3).replace(",", ""))
    
    if close_ts is None:
        return None
    
    return CanonicalKey(
        asset=asset,
        template=direction + "_STRIKE",
        interval="daily",
        strike=strike,
        close_ts=close_ts,
        outcome_definition=f"{asset} price {match.group(2).lower()} ${strike} at close",
    )

def _parse_kalshi_crypto_hourly(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse 'Ethereum up or down 1 hour?'"""
    title_lower = title.lower()
    
    match = re.match(
        r"^(bitcoin|btc|ethereum|eth)\s+(up\s+or\s+down|up|down)\s+(\d+)\s*(h|hour)",
        title_lower,
        re.IGNORECASE
    )
    if not match:
        return None
    
    asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
    asset = asset_map[match.group(1).lower()]
    interval = match.group(3) + "h"
    
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
# def normalize_limitless(raw_market: dict) -> MarketInfo:
#     """
#     Normalizer Limitless. Saat ini placeholder — akan dilengkapi saat kita
#     punya sampel data asli dari API Limitless.
    
#     Limitless hampir 100% crypto (BTC/ETH per jam/hari), jadi template-nya
#     akan fokus pada crypto up/down dan above-strike.
#     """
#     title = raw_market.get("title", raw_market.get("question", ""))
#     market_id = raw_market.get("id", raw_market.get("marketId", ""))
    
#     return MarketInfo(
#         venue="limitless",
#         venue_id=market_id,
#         title=title,
#         canonical_key=None,  # Placeholder
#         category="Crypto",
#         series=None,
#         is_parlay=False,
#         is_live_sport=False,
#         yes_price=None,
#         no_price=None,
#         liquidity_usd=None,
#         settlement_source="Limitless Official",
#         raw_data=raw_market,
#     )

def normalize_limitless(raw_market: dict) -> MarketInfo:
    """
    Normalizer Limitless — crypto hourly/daily up/down & above-strike.
    
    Contoh judul yang bisa di-parse:
    - "Bitcoin Up or Down 1 Hour"
    - "Ethereum Above $2500 by August 15"
    """
    title = raw_market.get("title", raw_market.get("question", ""))
    market_id = raw_market.get("id", raw_market.get("marketId", ""))
    end_date_iso = raw_market.get("endDate", raw_market.get("end_time", ""))
    
    # Parse waktu settlement
    close_ts = None
    if end_date_iso:
        try:
            dt = datetime.fromisoformat(end_date_iso.replace("Z", "+00:00"))
            close_ts = int(dt.timestamp())
        except (ValueError, AttributeError):
            pass
    
    # Attempt parse crypto hourly
    key = _parse_limitless_crypto_hourly(title, close_ts)
    
    # Attempt parse crypto daily above-strike
    if not key:
        key = _parse_limitless_crypto_above(title, close_ts)
    
    return MarketInfo(
        venue="limitless",
        venue_id=market_id,
        title=title,
        canonical_key=key,
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


def _parse_limitless_crypto_hourly(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse 'Bitcoin Up or Down 1 Hour'."""
    title_lower = title.lower()
    
    match = re.match(
        r"^(bitcoin|btc|ethereum|eth)\s+(up\s+or\s+down|up|down)\s+(\d+)\s*(h|hour)",
        title_lower,
        re.IGNORECASE
    )
    if not match:
        return None
    
    asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
    asset = asset_map[match.group(1).lower()]
    interval = match.group(3) + "h"
    
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


def _parse_limitless_crypto_above(title: str, close_ts: Optional[int]) -> Optional[CanonicalKey]:
    """Parse 'Ethereum Above $2500 by August 15'."""
    title_lower = title.lower()
    
    match = re.search(
        r"(bitcoin|btc|ethereum|eth)\s+(above|below)\s+\$?([\d,]+(?:\.\d+)?)",
        title_lower,
    )
    if not match:
        return None
    
    asset_map = {"bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH"}
    asset = asset_map[match.group(1).lower()]
    direction = "ABOVE" if match.group(2).lower() == "above" else "BELOW"
    strike = Decimal(match.group(3).replace(",", ""))
    
    if close_ts is None:
        return None
    
    return CanonicalKey(
        asset=asset,
        template=direction + "_STRIKE",
        interval="daily",
        strike=strike,
        close_ts=close_ts,
        outcome_definition=f"{asset} price {match.group(2).lower()} ${strike} at close",
    )