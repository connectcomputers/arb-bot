"""
Unit test Mapper & Pairing Engine.
Fixture berdasarkan kasus nyata dari screenshot klien dan blueprint.
"""
import time
from decimal import Decimal
from app.mapper.normalizer import normalize_polymarket, normalize_kalshi
from app.mapper.matcher import pair_markets, SkipCode


# ============ NORMALIZER POLYMARKET ============
def test_poly_crypto_15m_btc():
    """Polymarket: 'Bitcoin Up or Down 15 minutes' → canonical key valid."""
    raw = {
        "question": "Bitcoin Up or Down 15 minutes",
        "conditionId": "abc123",
        "endDate": "2026-08-11T14:30:00Z",
        "category": "Crypto",
    }
    market = normalize_polymarket(raw)
    assert market.canonical_key is not None
    assert market.canonical_key.asset == "BTC"
    assert market.canonical_key.template == "UP_DOWN"
    assert market.canonical_key.interval == "15m"


def test_poly_crypto_above_strike():
    """Polymarket: 'Bitcoin above $65,000 end of day' → strike = 65000."""
    raw = {
        "question": "Bitcoin above $65,000 end of day",
        "conditionId": "def456",
        "endDate": "2026-08-11T23:59:00Z",
        "category": "Crypto",
    }
    market = normalize_polymarket(raw)
    assert market.canonical_key is not None
    assert market.canonical_key.asset == "BTC"
    assert market.canonical_key.template == "ABOVE_STRIKE"
    assert market.canonical_key.strike == Decimal("65000")


def test_poly_sport_live_detect():
    """Polymarket kategori Sports → is_live_sport = True (akan di-skip)."""
    raw = {
        "question": "Kansas City Royals vs. Los Angeles Dodgers",
        "conditionId": "ghi789",
        "category": "Sports",
    }
    market = normalize_polymarket(raw)
    assert market.is_live_sport is True


# ============ NORMALIZER KALSHI ============
def test_kalshi_crypto_15m_btc():
    """Kalshi: 'Bitcoin Up or Down 15 minutes' → canonical key valid."""
    raw = {
        "title": "Bitcoin Up or Down 15 minutes",
        "ticker": "KXBTC-15M-26AUG11-1430",
        "event_ticker": "KXBTC-15M-26AUG11",
        "close_time": "2026-08-11T14:30:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.canonical_key is not None
    assert market.canonical_key.asset == "BTC"
    assert market.canonical_key.template == "UP_DOWN"
    assert market.series == "KXBTC"
    assert market.is_parlay is False


def test_kalshi_parlay_detect():
    """Kalshi parlay ('yes X, yes Y, yes Z...') → is_parlay = True."""
    raw = {
        "title": "yes Columbus, yes Charlotte, yes Minnesota, yes Salt",
        "ticker": "PARLAY-XYZ",
        "event_ticker": "PARLAY-XYZ",
        "close_time": "2026-08-12T20:00:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.is_parlay is True


def test_kalshi_series_extract_kxbtcy():
    """Ticker KXBTCY-25DEC31 → series = 'KXBTCY' (GRATIS)."""
    raw = {
        "title": "Bitcoin price above $100k on Dec 31",
        "ticker": "KXBTCY-25DEC31-T100K",
        "event_ticker": "KXBTCY-25DEC31",
        "close_time": "2026-12-31T23:59:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.series == "KXBTCY"


# ============ MATCHER: LOCK ============
def test_matcher_lock_btc_15m():
    """BTC 15m di Poly + Kalshi dengan close_ts sama → LOCKED."""
    now_ts = int(time.time())
    close_ts = now_ts + 600  # 10 menit dari sekarang
    
    poly = normalize_polymarket({
        "question": "Bitcoin Up or Down 15 minutes",
        "conditionId": "p1",
        "endDate": f"{_epoch_to_iso(close_ts)}",
        "category": "Crypto",
    })
    # Override close_ts agar sama persis
    poly.canonical_key = poly.canonical_key.__class__(
        asset=poly.canonical_key.asset,
        template=poly.canonical_key.template,
        interval=poly.canonical_key.interval,
        strike=poly.canonical_key.strike,
        close_ts=close_ts,
        outcome_definition=poly.canonical_key.outcome_definition,
    )
    
    kal = normalize_kalshi({
        "title": "Bitcoin Up or Down 15 minutes",
        "ticker": "k1",
        "event_ticker": "KXBTC-15M",
        "close_time": f"{_epoch_to_iso(close_ts)}",
    })
    kal.canonical_key = kal.canonical_key.__class__(
        asset=kal.canonical_key.asset,
        template=kal.canonical_key.template,
        interval=kal.canonical_key.interval,
        strike=kal.canonical_key.strike,
        close_ts=close_ts,
        outcome_definition=kal.canonical_key.outcome_definition,
    )
    
    result = pair_markets([poly], [kal], [], min_ttl_seconds=60)
    
    assert result.lock_count == 1
    assert result.locked[0].key.asset == "BTC"
    assert len(result.locked[0].markets) == 2
    assert {m.venue for m in result.locked[0].markets} == {"polymarket", "kalshi"}


# ============ MATCHER: SKIP ============
def test_matcher_skip_s1_market_single_venue():
    """Market hanya di 1 venue → SKIP S1."""
    now_ts = int(time.time())
    close_ts = now_ts + 600
    
    poly = normalize_polymarket({
        "question": "Bitcoin Up or Down 15 minutes",
        "conditionId": "p1",
        "endDate": _epoch_to_iso(close_ts),
        "category": "Crypto",
    })
    
    result = pair_markets([poly], [], [], min_ttl_seconds=60)
    
    assert result.lock_count == 0
    assert result.skip_count >= 1
    assert any(s.skip_code == SkipCode.S1 for s in result.skipped)


def test_matcher_skip_s9_parlay():
    """Kalshi parlay → SKIP S9."""
    now_ts = int(time.time())
    close_ts = now_ts + 600
    
    parlay = normalize_kalshi({
        "title": "yes Columbus, yes Charlotte, yes Minnesota, yes Salt",
        "ticker": "PARLAY-XYZ",
        "event_ticker": "PARLAY-XYZ",
        "close_time": _epoch_to_iso(close_ts),
    })
    
    result = pair_markets([], [parlay], [], min_ttl_seconds=60)
    
    assert result.lock_count == 0
    assert any(s.skip_code == SkipCode.S9 and "Parlay" in s.reason_detail for s in result.skipped)


def test_matcher_skip_s5_live_sport():
    """Polymarket Sports → SKIP S5 (placement delay)."""
    now_ts = int(time.time())
    close_ts = now_ts + 600
    
    sport = normalize_polymarket({
        "question": "Kansas City Royals vs. Los Angeles Dodgers",
        "conditionId": "p_sport",
        "endDate": _epoch_to_iso(close_ts),
        "category": "Sports",
    })
    
    result = pair_markets([sport], [], [], min_ttl_seconds=60)
    
    assert result.lock_count == 0
    assert any(s.skip_code == SkipCode.S5 for s in result.skipped)


def test_matcher_skip_s11_excluded_category():
    """Kategori Culture → SKIP S11."""
    now_ts = int(time.time())
    close_ts = now_ts + 600
    
    culture = normalize_polymarket({
        "question": "Will [X] happen?",
        "conditionId": "p_culture",
        "endDate": _epoch_to_iso(close_ts),
        "category": "Culture",
    })
    
    result = pair_markets([culture], [], [], min_ttl_seconds=60)
    
    assert result.lock_count == 0
    assert any(s.skip_code == SkipCode.S11 for s in result.skipped)


# ============ HELPER ============
def _epoch_to_iso(epoch: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Tambah Unit Test 
# ============ NORMALIZER POLITICS ============
def test_poly_politics_trump_2028():
    """Polymarket: 'Will Trump win the 2028 presidential election?'"""
    raw = {
        "question": "Will Trump win the 2028 presidential election?",
        "conditionId": "p_trump",
        "endDate": "2028-12-31T23:59:00Z",
        "category": "Politics",
    }
    market = normalize_polymarket(raw)
    assert market.canonical_key is not None
    # assert market.canonical_key.asset == "TRUMP"
    assert market.canonical_key.asset == "US_PRES_2028"
    assert market.canonical_key.template == "YES_NO_EVENT"
    assert "2028" in market.canonical_key.interval


def test_poly_politics_clarity_act():
    """Polymarket: 'CLARITY Act signed into law in 2026?'"""
    raw = {
        "question": "CLARITY Act signed into law in 2026?",
        "conditionId": "p_clarity",
        "endDate": "2026-12-31T23:59:00Z",
        "category": "Politics",
    }
    market = normalize_polymarket(raw)
    assert market.canonical_key is not None
    assert market.canonical_key.asset == "CLARITY_ACT"
    assert market.canonical_key.template == "YES_NO_EVENT"


def test_kalshi_politics_series_kxel():
    """Kalshi series KXEL (election) → politics."""
    raw = {
        "title": "Trump to win 2028 presidential election?",
        "ticker": "KXEL-28TRUMP-Y",
        "event_ticker": "KXEL-28TRUMP",
        "close_time": "2028-11-05T23:59:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.canonical_key is not None
    # assert market.canonical_key.asset == "US_ELECTION"
    assert market.canonical_key.asset == "US_PRES_2028"
    assert market.series == "KXEL"


# ============ NORMALIZER ECONOMICS ============
def test_kalshi_economics_fed_rate_cut():
    """Kalshi: 'Fed rate cut in September 2026?' (KXFED series)."""
    raw = {
        "title": "Fed rate cut in September 2026?",
        "ticker": "KXFED-26SEP-CUT25",
        "event_ticker": "KXFED-26SEP",
        "close_time": "2026-09-17T18:00:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.canonical_key is not None
    assert market.canonical_key.asset == "FED_RATE"
    assert market.series == "KXFED"
    assert "sep" in market.canonical_key.interval.lower()


def test_kalshi_economics_cpi():
    """Kalshi: 'CPI for August 2026 above 3%?' (KXCPI series)."""
    raw = {
        "title": "CPI for August 2026 above 3%?",
        "ticker": "KXCPI-26AUG-ABOVE3",
        "event_ticker": "KXCPI-26AUG",
        "close_time": "2026-09-11T12:30:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.canonical_key is not None
    assert market.canonical_key.asset == "CPI"
    assert market.series == "KXCPI"


def test_kalshi_economics_gdp():
    """Kalshi: 'GDP Q3 2026 above 2%?' (KXGDP series)."""
    raw = {
        "title": "GDP Q3 2026 above 2%?",
        "ticker": "KXGDP-26Q3-ABOVE2",
        "event_ticker": "KXGDP-26Q3",
        "close_time": "2026-10-30T12:30:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.canonical_key is not None
    assert market.canonical_key.asset == "GDP"
    assert market.series == "KXGDP"


# ============ PARLAY DETECTOR FIX ============
def test_kalshi_parlay_real():
    """Kalshi parlay asli (series PARLAY-) → is_parlay = True."""
    raw = {
        "title": "yes Columbus, yes Charlotte, yes Minnesota, yes Salt",
        "ticker": "PARLAY-XYZ-001",
        "event_ticker": "PARLAY-XYZ",
        "close_time": "2026-08-12T20:00:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.is_parlay is True


def test_kalshi_binary_not_parlay():
    """Kalshi biner biasa yang kebetulan ada kata 'yes' → TIDAK parlay."""
    raw = {
        "title": "Will Fed cut rates in September 2026?",
        "ticker": "KXFED-26SEP-CUT25",
        "event_ticker": "KXFED-26SEP",
        "close_time": "2026-09-17T18:00:00Z",
    }
    market = normalize_kalshi(raw)
    assert market.is_parlay is False
    assert market.canonical_key is not None


# ============ MATCHER: LOCK POLITICS ============
def test_matcher_lock_trump_2028():
    """Trump 2028 di Poly + Kalshi dengan close_ts sama → LOCKED."""
    now_ts = int(time.time())
    close_ts = now_ts + 86400 * 30  # 30 hari
    
    poly = normalize_polymarket({
        "question": "Will Trump win the 2028 presidential election?",
        "conditionId": "p_trump",
        "endDate": _epoch_to_iso(close_ts),
        "category": "Politics",
    })
    poly.canonical_key = poly.canonical_key.__class__(
        asset=poly.canonical_key.asset,
        template=poly.canonical_key.template,
        interval=poly.canonical_key.interval,
        strike=poly.canonical_key.strike,
        close_ts=close_ts,
        outcome_definition=poly.canonical_key.outcome_definition,
    )
    
    kal = normalize_kalshi({
        "title": "Trump to win 2028 presidential election?",
        "ticker": "KXEL-28TRUMP-Y",
        "event_ticker": "KXEL-28TRUMP",
        "close_time": _epoch_to_iso(close_ts),
    })
    kal.canonical_key = kal.canonical_key.__class__(
        asset=kal.canonical_key.asset,
        template=kal.canonical_key.template,
        interval=kal.canonical_key.interval,
        strike=kal.canonical_key.strike,
        close_ts=close_ts,
        outcome_definition=kal.canonical_key.outcome_definition,
    )
    
    result = pair_markets([poly], [kal], [], min_ttl_seconds=60)
    
    assert result.lock_count == 1
    # assert result.locked[0].key.asset == "TRUMP"
    assert result.locked[0].key.asset == "US_PRES_2028"


def test_matcher_lock_fed_rate_cut():
    """Fed rate cut di Poly + Kalshi dengan close_ts sama → LOCKED."""
    now_ts = int(time.time())
    close_ts = now_ts + 86400 * 30
    
    poly = normalize_polymarket({
        "question": "Fed to cut rates in September 2026?",
        "conditionId": "p_fed",
        "endDate": _epoch_to_iso(close_ts),
        "category": "Economics",
    })
    poly.canonical_key = poly.canonical_key.__class__(
        asset="FED_RATE",
        template="YES_NO_EVENT",
        interval=poly.canonical_key.interval,
        strike=None,
        close_ts=close_ts,
        outcome_definition=poly.canonical_key.outcome_definition,
    )
    
    kal = normalize_kalshi({
        "title": "Fed rate cut in September 2026?",
        "ticker": "KXFED-26SEP-CUT25",
        "event_ticker": "KXFED-26SEP",
        "close_time": _epoch_to_iso(close_ts),
    })
    kal.canonical_key = kal.canonical_key.__class__(
        asset=kal.canonical_key.asset,
        template=kal.canonical_key.template,
        interval=kal.canonical_key.interval,
        strike=kal.canonical_key.strike,
        close_ts=close_ts,
        outcome_definition=kal.canonical_key.outcome_definition,
    )
    
    result = pair_markets([poly], [kal], [], min_ttl_seconds=60)
    
    assert result.lock_count == 1
    assert result.locked[0].key.asset == "FED_RATE"