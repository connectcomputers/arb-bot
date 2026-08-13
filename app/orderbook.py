"""
Orderbook fetcher: mengambil harga YES/NO real dari tiap venue.
"""
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "application/json",
}


@dataclass
class OrderbookSnapshot:
    """Snapshot harga terbaik dari satu market di satu venue."""
    venue: str
    yes_best_ask: Optional[Decimal]  # harga terendah yang bisa kita beli YES
    no_best_ask: Optional[Decimal]   # harga terendah yang bisa kita beli NO
    yes_best_bid: Optional[Decimal]
    no_best_bid: Optional[Decimal]
    yes_liquidity: Optional[Decimal] = None
    no_liquidity: Optional[Decimal] = None


# ==========================
# KALSHI
# ==========================
async def fetch_kalshi_orderbook(client: httpx.AsyncClient, ticker: str) -> OrderbookSnapshot:
    """
    Ambil orderbook Kalshi. Endpoint publik, tidak perlu auth.
    Response: {"market": {...}, "orderbook": {"yes": [...], "no": [...]}}
    Tiap level: {"price": "45", "quantity": "100"}
    """
    url = f"https://external-api.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15.0)
        if resp.status_code != 200:
            return OrderbookSnapshot("kalshi", None, None, None, None)
        
        data = resp.json()
        ob = data.get("orderbook", {})
        
        # Parse level YES (asks = yang bisa kita beli; bids = yang bisa kita jual)
        yes_asks = sorted(ob.get("yes", []), key=lambda x: float(x.get("price", 0)))
        no_asks = sorted(ob.get("no", []), key=lambda x: float(x.get("price", 0)))
        yes_bids = sorted(ob.get("yes", []), key=lambda x: -float(x.get("price", 0)))
        no_bids = sorted(ob.get("no", []), key=lambda x: -float(x.get("price", 0)))
        
        # Kalshi harga dalam satuan sen (integer 1-99), ubah ke desimal
        yes_best_ask = Decimal(yes_asks[0]["price"]) / 100 if yes_asks else None
        no_best_ask = Decimal(no_asks[0]["price"]) / 100 if no_asks else None
        yes_best_bid = Decimal(yes_bids[0]["price"]) / 100 if yes_bids else None
        no_best_bid = Decimal(no_bids[0]["price"]) / 100 if no_bids else None
        
        return OrderbookSnapshot(
            venue="kalshi",
            yes_best_ask=yes_best_ask, no_best_ask=no_best_ask,
            yes_best_bid=yes_best_bid, no_best_bid=no_best_bid,
        )
    except Exception:
        return OrderbookSnapshot("kalshi", None, None, None, None)


# ==========================
# POLYMARKET
# ==========================
async def fetch_polymarket_orderbook(client: httpx.AsyncClient, condition_id: str) -> OrderbookSnapshot:
    """
    Ambil orderbook Polymarket via CLOB API publik.
    Pertama, kita perlu dapat token_id YES dan NO dari market.
    Endpoint: https://clob.polymarket.com/markets/{condition_id}
    """
    # Step 1: dapat token_ids
    url_market = f"https://clob.polymarket.com/markets/{condition_id}"
    try:
        resp = await client.get(url_market, headers=HEADERS, timeout=15.0)
        if resp.status_code != 200:
            # Coba endpoint gamma sebagai fallback
            return await _fetch_poly_fallback(client, condition_id)
        
        data = resp.json()
        tokens = data.get("tokens", [])
        if not tokens:
            return OrderbookSnapshot("polymarket", None, None, None, None)
        
        yes_token = next((t for t in tokens if t.get("outcome", "").upper() == "YES"), None)
        no_token = next((t for t in tokens if t.get("outcome", "").upper() == "NO"), None)
        
        if not yes_token or not no_token:
            return OrderbookSnapshot("polymarket", None, None, None, None)
        
        # Step 2: ambil book untuk YES dan NO
        yes_book = await _fetch_poly_book(client, yes_token["token_id"])
        no_book = await _fetch_poly_book(client, no_token["token_id"])
        
        return OrderbookSnapshot(
            venue="polymarket",
            yes_best_ask=yes_book["ask"], no_best_ask=no_book["ask"],
            yes_best_bid=yes_book["bid"], no_best_bid=no_book["bid"],
        )
    except Exception:
        return OrderbookSnapshot("polymarket", None, None, None, None)


async def _fetch_poly_book(client: httpx.AsyncClient, token_id: str) -> dict:
    """Ambil best ask/bid untuk satu token Polymarket."""
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15.0)
        if resp.status_code != 200:
            return {"ask": None, "bid": None}
        
        data = resp.json()
        asks = data.get("asks", [])
        bids = data.get("bids", [])
        
        # Polymarket harga dalam desimal (0.01-0.99)
        best_ask = None
        if asks:
            best_ask = Decimal(min(asks, key=lambda x: float(x.get("price", 1)))["price"])
        
        best_bid = None
        if bids:
            best_bid = Decimal(max(bids, key=lambda x: float(x.get("price", 0)))["price"])
        
        return {"ask": best_ask, "bid": best_bid}
    except Exception:
        return {"ask": None, "bid": None}


async def _fetch_poly_fallback(client: httpx.AsyncClient, condition_id: str) -> OrderbookSnapshot:
    """Fallback: pakai gamma API yang mengembalikan outcomePrices langsung."""
    url = "https://gamma-api.polymarket.com/markets"
    try:
        resp = await client.get(url, params={"id": condition_id}, headers=HEADERS, timeout=15.0)
        if resp.status_code != 200:
            return OrderbookSnapshot("polymarket", None, None, None, None)
        
        markets = resp.json()
        if not markets:
            return OrderbookSnapshot("polymarket", None, None, None, None)
        
        m = markets[0]
        prices_str = m.get("outcomePrices", "")
        if not prices_str:
            return OrderbookSnapshot("polymarket", None, None, None, None)
        
        # Format: "[\"0.45\", \"0.55\"]" atau "0.45,0.55"
        import json
        try:
            prices = json.loads(prices_str)
        except Exception:
            prices = [p.strip() for p in prices_str.split(",")]
        
        if len(prices) >= 2:
            return OrderbookSnapshot(
                "polymarket",
                Decimal(str(prices[0])), Decimal(str(prices[1])),
                None, None,
            )
        return OrderbookSnapshot("polymarket", None, None, None, None)
    except Exception:
        return OrderbookSnapshot("polymarket", None, None, None, None)

# ==========================
# LIMITLESS
# ==========================
async def fetch_limitless_orderbook(client: httpx.AsyncClient, market_id: str) -> OrderbookSnapshot:
    """
    Ambil orderbook Limitless via CLOB API publik.
    Endpoint: https://api.limitless.exchange/v1/markets/{market_id}/orderbook
    """
    url = f"https://api.limitless.exchange/v1/markets/{market_id}/orderbook"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15.0)
        if resp.status_code != 200:
            return OrderbookSnapshot("limitless", None, None, None, None)
        
        data = resp.json()
        asks = data.get("asks", [])
        bids = data.get("bids", [])
        
        # Limitless harga dalam desimal (mirip Polymarket)
        best_ask = None
        if asks:
            best_ask = Decimal(min(asks, key=lambda x: float(x.get("price", 1)))["price"])
        
        best_bid = None
        if bids:
            best_bid = Decimal(max(bids, key=lambda x: float(x.get("price", 0)))["price"])
        
        # Limitless hanya punya YES/NO tunggal (tidak terpisah)
        return OrderbookSnapshot(
            venue="limitless",
            yes_best_ask=best_ask, no_best_ask=best_ask,  # sama untuk YES dan NO
            yes_best_bid=best_bid, no_best_bid=best_bid,
        )
    except Exception:
        return OrderbookSnapshot("limitless", None, None, None, None)    