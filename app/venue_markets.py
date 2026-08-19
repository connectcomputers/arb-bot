"""Ambil 5 populer + 5 aktif per venue untuk daftar Pair."""
import httpx

CAT_RULES = [
    ("crypto", ["btc", "bitcoin", "eth", "ethereum", "solana", "doge", "crypto", "xrp", "kxcrypto"]),
    ("politik", ["president", "election", "senate", "governor", "congress", "prime minister",
                 "mayor", "democratic", "republican", "trump", "kxelec", "kxpol"]),
    ("geopolitik", ["war", "ceasefire", "troops", "sanctions", "nuclear", "strait of hormuz",
                    "ukraine", "russia", "china", "taiwan", "iran", "israel", "gaza"]),
    ("olahraga", ["nba", "nfl", "mlb", "nhl", "football", "soccer", "tennis", "ufc",
                  "olympic", "world cup", "kxsports", "lakers", "real madrid"]),
    ("esports", ["esports", "league of legends", "dota", "cs2", "valorant", "fnatic"]),
    ("ekonomi", ["inflation", "cpi", "gdp", "fomc", "rate cut", "interest rate",
                 "unemployment", "kxecon"]),
    ("keuangan", ["s&p", "nasdaq", "dow jones", "stock", "ipo", "spacex", "tesla", "apple", "kxfin"]),
    ("teknologi", ["openai", "iphone", "starlink", "artificial intelligence", "kxtech"]),
    ("budaya", ["oscar", "grammy", "movie", "album", "kxculture"]),
    ("cuaca", ["hurricane", "temperature", "weather", "tornado"]),
]


def classify(title: str, ticker: str = "") -> str:
    t = (title + " " + (ticker or "")).lower()
    for cat, kws in CAT_RULES:
        if any(k in t for k in kws):
            return cat
    return "lainnya"


# def venue_categories(venue: str, creds: dict):
#     """Menu pair venue: kategori yang punya market aktif, + jumlah marketnya."""
#     try:
#         rows = FETCH[venue](creds or {})
#     except Exception:
#         return []
#     counts = {}
#     for r in rows:
#         c = classify(r["title"], r["key"])
#         counts[c] = counts.get(c, 0) + 1
#     return [{"name": k, "count": v}
#             for k, v in sorted(counts.items(), key=lambda x: -x[1])]

def venue_categories(venue: str, creds: dict):
    """Menu pair: top-10 kategori (tanpa 'lainnya'), urut volume 24j (populer)."""
    try:
        rows = FETCH[venue](creds or {})
    except Exception:
        return []
    agg = {}
    for r in rows:
        c = classify(r["title"], r["key"])
        if c == "lainnya":
            continue
        a = agg.setdefault(c, {"count": 0, "vol": 0.0})
        a["count"] += 1
        a["vol"] += r["vol"]
    cats = [{"name": k, "count": v["count"], "vol": v["vol"]}
            for k, v in agg.items()]
    cats.sort(key=lambda x: x["vol"], reverse=True)   # paling populer dulu
    return cats[:10]                                  # maks 10 menu

def _cat_kalshi(ticker: str) -> str:
    t = (ticker or "").upper()
    if t.startswith("KXCRYPTO") or "BTC" in t or "ETH" in t:
        return "crypto"
    if t.startswith("KXECON"):
        return "ekonomi"
    if "ELECT" in t or "POL" in t:
        return "politik"
    return "lainnya"


def _poly(creds):
    r = httpx.get("https://gamma-api.polymarket.com/markets", params={
        "closed": "false", "limit": 30,
        "order": "volume24hr", "ascending": "false"}, timeout=15)
    return [{
        "key": m.get("conditionId") or str(m.get("id")),
        "title": (m.get("question") or "?")[:70],
        "cat": m.get("category") or "lainnya",
        "vol": float(m.get("volume24hr") or 0),
        "liq": float(m.get("liquidity") or 0),
    } for m in r.json()]


def _kalshi(creds):
    base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
    r = httpx.get(base + "/trade-api/v2/markets",
                  params={"limit": 100, "status": "open"}, timeout=15)
    return [{
        "key": m.get("ticker"),
        "title": (m.get("title") or m.get("subtitle") or "?")[:70],
        "cat": _cat_kalshi(m.get("ticker")),
        "vol": float(m.get("volume") or 0),
        "liq": float(m.get("liquidity") or 0),
    } for m in r.json().get("markets", [])]


def _limitless(creds):
    r = httpx.get("https://api.limitless.exchange/markets/active",
                  params={"limit": 25}, timeout=15)
    return [{
        "key": m.get("slug"),
        "title": (m.get("title") or "?")[:70],
        "cat": (m.get("categories") or ["lainnya"])[0],
        "vol": float(m.get("volumeFormatted") or 0),
        "liq": float(m.get("liquidityFormatted") or 0),
    } for m in r.json().get("data", [])]


FETCH = {"polymarket": _poly, "kalshi": _kalshi, "limitless": _limitless}


def top_markets(venue: str, creds: dict):
    try:
        rows = FETCH[venue](creds or {})
    except Exception:
        return {"populer": [], "aktif": []}
    populer = sorted(rows, key=lambda x: x["vol"], reverse=True)[:5]
    keys = {p["key"] for p in populer}
    aktif = sorted([r for r in rows if r["key"] not in keys],
                   key=lambda x: x["liq"], reverse=True)[:5]
    return {"populer": populer, "aktif": aktif}