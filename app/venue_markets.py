"""Menu pair per venue — versi final self-consistent."""
import httpx

NATIVE_MAP = {
    "crypto": "crypto", "cryptocurrencies": "crypto",
    "politics": "politik", "elections": "politik", "election": "politik", "mentions": "politik",
    "geopolitics": "geopolitik", "world": "geopolitik", "international": "geopolitik",
    "sports": "olahraga", "sport": "olahraga",
    "esports": "esports", "e-sports": "esports",
    "economics": "ekonomi", "econ": "ekonomi",
    "finance": "keuangan", "financials": "keuangan", "financial": "keuangan",
    "tech": "teknologi", "technology": "teknologi", "science": "teknologi",
    "tech & science": "teknologi",
    "culture": "budaya", "entertainment": "budaya",
    "climate": "cuaca", "weather": "cuaca",
}

KALSHI_SERIES = [
    ("crypto", ["kxbtc", "kxeth", "kxsol", "kxdoge", "kxcrypto", "kxcoin"]),
    ("ekonomi", ["kxcpi", "kxfed", "kxgdp", "kxjobs", "kxecon", "kxinfl", "kxrate", "kxfomc"]),
    ("politik", ["kxelec", "kxpol", "kxcong", "kxsen", "kxgov", "kxpres", "kxcourt", "kxhouse"]),
    ("geopolitik", ["kxwar", "kxgeo", "kxchina", "kxruss", "kxiran", "kxisrael", "kxtaiwan"]),
    ("olahraga", ["kxmlb", "kxnba", "kxnfl", "kxnhl", "kxepl", "kxucl", "kxfifa", "kxgolf",
                  "kxtenn", "kxufc", "kxoly", "kxncaa", "kxf1", "kxwnba", "kxpga"]),
    ("esports", ["kxes", "kxlol", "kxdota", "kxcs", "kxval"]),
    ("keuangan", ["kxspx", "kxndx", "kxdji", "kxstock", "kxfin", "kxgold", "kxoil", "kxcommod"]),
    ("teknologi", ["kxai", "kxtech", "kxspace"]),
    ("budaya", ["kxmov", "kxmus", "kxoscar", "kxcult", "kxgrammy"]),
    ("cuaca", ["kxhurr", "kxtemp", "kxclim", "kxweath"]),
]

CAT_RULES = [
    ("crypto", ["btc", "bitcoin", "eth", "ethereum", "solana", "doge", "crypto", "xrp",
                "bnb", "avax", "ltc", "ada ", "link", "up or down"]),
    ("politik", ["president", "election", "senate", "governor", "congress", "prime minister",
                 "mayor", "democratic", "republican", "trump", "biden", "zelensky", "putin",
                 "referendum", "primary", "ballot"]),
    ("geopolitik", ["war", "ceasefire", "troops", "sanctions", "nuclear", "strait of hormuz",
                    "ukraine", "russia", "china", "taiwan", "iran", "israel", "gaza",
                    "capture", "donetsk", "luhansk", "missile", "frontline", "invasion"]),
    ("olahraga", ["nba", "nfl", "mlb", "nhl", "football", "soccer", "tennis", "ufc",
                  "olympic", "world cup", "lakers", "real madrid", "formula 1", "grand prix",
                  "wimbledon", "messi", "ronaldo"]),
    ("esports", ["esports", "league of legends", "dota", "cs2", "valorant", "fnatic",
                 "lck", "lpl", "worlds", "msi", "vct", "dplus", "gen.g", "g2 ", "t1 "]),
    ("ekonomi", ["inflation", "cpi", "gdp", "fomc", "rate cut", "interest rate",
                 "unemployment", "jobs report", "payroll", "recession"]),
    ("keuangan", ["s&p", "nasdaq", "dow jones", "stock", "ipo", "spacex", "tesla", "apple",
                  "gold", "xauusd", "silver", "oil", "wti", "fed decision", "spy",
                  "earnings", "dividend"]),
    ("teknologi", ["openai", "iphone", "starlink", "artificial intelligence", "gpt", "starship"]),
    ("budaya", ["oscar", "grammy", "movie", "album"]),
    ("cuaca", ["hurricane", "temperature", "weather", "tornado"]),
]

VOL_KEYS = ("volume_24h_fp", "volume_fp", "volume_24h", "volume24h", "volume24hr",
            "volumeNum", "volumeFormatted", "daily_volume", "volume")
LIQ_KEYS = ("liquidity_dollars", "liquidityFormatted", "liquidity", "open_interest")


def _num(m, keys):
    for k in keys:
        v = m.get(k)
        if v:
            try:
                return float(v)
            except Exception:
                continue
    return 0.0


def _vol(m):
    return _num(m, VOL_KEYS)


def _liq(m):
    return _num(m, LIQ_KEYS)


def norm(native):
    if isinstance(native, list):
        for n in native:
            c = NATIVE_MAP.get((n or "").strip().lower())
            if c:
                return c
        return None
    return NATIVE_MAP.get((native or "").strip().lower())


def classify(title: str, ticker: str = "") -> str:
    t = (title + " " + (ticker or "")).lower()
    for cat, kws in CAT_RULES:
        if any(k in t for k in kws):
            return cat
    return "lainnya"


def classify_kalshi(title: str, ticker: str) -> str:
    tk = (ticker or "").lower()
    for cat, pats in KALSHI_SERIES:
        if any(p in tk for p in pats):
            return cat
    return classify(title, ticker)


# def _poly(creds):
#     r = httpx.get("https://gamma-api.polymarket.com/markets", params={
#         "closed": "false", "limit": 200,
#         "order": "volume24hr", "ascending": "false"}, timeout=20)
#     return [{
#         "key": m.get("conditionId") or str(m.get("id")),
#         "title": (m.get("question") or "?")[:70],
#         "cat": norm(m.get("category")) or classify(m.get("question") or ""),
#         "vol": _vol(m), "liq": _liq(m),
#     } for m in r.json()]

def _poly(creds):
    r = httpx.get("https://gamma-api.polymarket.com/markets", params={
        "closed": "false", "limit": 200,
        "order": "volume24hr", "ascending": "false"}, timeout=20)
    return [{
        "key": m.get("conditionId") or str(m.get("id")),
        "title": (m.get("question") or "?")[:70],
        "cat": norm(m.get("category")) or classify(m.get("question") or ""),
        "vol": _vol(m), "liq": _liq(m),
        "yes": float(m.get("bestAsk") or m.get("lastTradePrice") or 0),
    } for m in r.json()]

# def _kalshi(creds):
#     base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
#     r = None
#     for lim in (1000, 500, 200):
#         r = httpx.get(base + "/trade-api/v2/markets",
#                       params={"limit": lim, "status": "open"}, timeout=25)
#         if r.status_code == 200:
#             break
#     rows = []
#     for m in r.json().get("markets", []):
#         tick = m.get("ticker") or ""
#         if tick.startswith("KXMVE"):
#             continue
#         text = " ".join(filter(None, [m.get("title"), m.get("yes_sub_title"),
#                                       m.get("no_sub_title")]))
#         rows.append({"key": tick, "title": (m.get("title") or "?")[:70],
#                     #  "cat": classify_kalshi(text, tick),
#                     #  "vol": _vol(m), "liq": _liq(m)})
#                      "cat": classify_kalshi(text, tick),
#                      "vol": max(_vol(m), float(m.get("volume_fp") or 0)),   # ← 24j atau total
#                      "liq": _liq(m)})                    
#     if len(rows) < 30:
#         try:
#             rs = httpx.get(base + "/trade-api/v2/series",
#                            params={"limit": 200}, timeout=20)
#             for s in rs.json().get("series", []):
#                 rows.append({"key": s.get("ticker"),
#                              "title": (s.get("title") or "?")[:70],
#                              "cat": norm(s.get("category")) or
#                                     classify(s.get("title") or "", s.get("ticker") or ""),
#                              "vol": _vol(s), "liq": _liq(s)})
#         except Exception:
#             pass
#     return rows

def _kalshi(creds):
    base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
    r = None
    for lim in (1000, 500, 200):
        r = httpx.get(base + "/trade-api/v2/markets",
                      params={"limit": lim, "status": "open"}, timeout=25)
        if r.status_code == 200:
            break
    rows = []
    for m in r.json().get("markets", []):
        tick = m.get("ticker") or ""
        if tick.startswith("KXMVE"):
            continue
        text = " ".join(filter(None, [m.get("title"), m.get("yes_sub_title"),
                                      m.get("no_sub_title")]))
        rows.append({"key": tick, "title": (m.get("title") or "?")[:70],
                     "cat": classify_kalshi(text, tick),
                     "vol": max(_vol(m), float(m.get("volume_fp") or 0)),
                     "liq": _liq(m),
                     "yes": (float(m.get("yes_bid_dollars") or 0) +
                             float(m.get("yes_ask_dollars") or 0)) / 2})
    if len(rows) < 30:
        try:
            rs = httpx.get(base + "/trade-api/v2/series",
                           params={"limit": 200}, timeout=20)
            for s in rs.json().get("series", []):
                rows.append({"key": s.get("ticker"),
                             "title": (s.get("title") or "?")[:70],
                             "cat": norm(s.get("category")) or
                                    classify(s.get("title") or "", s.get("ticker") or ""),
                             "vol": _vol(s), "liq": _liq(s),
                             "yes": 0.0})
        except Exception:
            pass
    return rows

# def _limitless(creds):
#     seen = {}
#     for sort in (None, "newest", "ending_soon"):
#         for page in (1, 2, 3, 4):
#             params = {"limit": 25, "page": page}
#             if sort:
#                 params["sortBy"] = sort
#             try:
#                 r = httpx.get("https://api.limitless.exchange/markets/active",
#                               params=params, timeout=15)
#                 data = r.json().get("data", [])
#             except Exception:
#                 break
#             if not data:
#                 break
#             for m in data:
#                 seen.setdefault(m.get("slug"), m)
#     return [{
#         "key": m.get("slug"),
#         "title": (m.get("title") or "?")[:70],
#         "cat": norm(m.get("categories")) or
#                classify(m.get("title") or "", m.get("slug") or ""),
#         "vol": _vol(m), "liq": _liq(m),
#     } for m in seen.values()]

def _limitless(creds):
    seen = {}
    for sort in (None, "newest", "ending_soon"):
        for page in (1, 2, 3, 4):
            params = {"limit": 25, "page": page}
            if sort:
                params["sortBy"] = sort
            try:
                r = httpx.get("https://api.limitless.exchange/markets/active",
                              params=params, timeout=15)
                data = r.json().get("data", [])
            except Exception:
                break
            if not data:
                break
            for m in data:
                seen.setdefault(m.get("slug"), m)
    return [{
        "key": m.get("slug"),
        "title": (m.get("title") or "?")[:70],
        "cat": norm(m.get("categories")) or
               classify(m.get("title") or "", m.get("slug") or ""),
        "vol": _vol(m), "liq": _liq(m),
        "yes": (m.get("prices") or [0, 0])[0] / 100,
    } for m in seen.values()]

FETCH = {"polymarket": _poly, "kalshi": _kalshi, "limitless": _limitless}


def venue_categories(venue: str, creds: dict):
    try:
        rows = FETCH[venue](creds or {})
    except Exception:
        return []
    agg = {}
    for r in rows:
        c = r["cat"]
        if not c or c == "lainnya":
            continue
        a = agg.setdefault(c, {"count": 0, "vol": 0.0})
        a["count"] += 1
        a["vol"] += r["vol"]
    cats = [{"name": k, "count": v["count"], "vol": v["vol"]} for k, v in agg.items()]
    cats.sort(key=lambda x: x["vol"], reverse=True)
    return cats[:10]

# =====================================================================================
# """Ambil 5 populer + 5 aktif per venue untuk daftar Pair."""
# import httpx

# # CAT_RULES = [
# #     ("crypto", ["btc", "bitcoin", "eth", "ethereum", "solana", "doge", "crypto", "xrp", "kxcrypto"]),
# #     ("politik", ["president", "election", "senate", "governor", "congress", "prime minister",
# #                  "mayor", "democratic", "republican", "trump", "kxelec", "kxpol"]),
# #     ("geopolitik", ["war", "ceasefire", "troops", "sanctions", "nuclear", "strait of hormuz",
# #                     "ukraine", "russia", "china", "taiwan", "iran", "israel", "gaza"]),
# #     ("olahraga", ["nba", "nfl", "mlb", "nhl", "football", "soccer", "tennis", "ufc",
# #                   "olympic", "world cup", "kxsports", "lakers", "real madrid"]),
# #     ("esports", ["esports", "league of legends", "dota", "cs2", "valorant", "fnatic"]),
# #     ("ekonomi", ["inflation", "cpi", "gdp", "fomc", "rate cut", "interest rate",
# #                  "unemployment", "kxecon"]),
# #     ("keuangan", ["s&p", "nasdaq", "dow jones", "stock", "ipo", "spacex", "tesla", "apple", "kxfin"]),
# #     ("teknologi", ["openai", "iphone", "starlink", "artificial intelligence", "kxtech"]),
# #     ("budaya", ["oscar", "grammy", "movie", "album", "kxculture"]),
# #     ("cuaca", ["hurricane", "temperature", "weather", "tornado"]),
# # ]

# NATIVE_MAP = {
#     "crypto": "crypto", "cryptocurrencies": "crypto",
#     "politics": "politik", "elections": "politik", "election": "politik", "mentions": "politik",
#     "geopolitics": "geopolitik", "world": "geopolitik", "international": "geopolitik",
#     "sports": "olahraga", "sport": "olahraga",
#     "esports": "esports", "e-sports": "esports",
#     "economics": "ekonomi", "econ": "ekonomi",
#     "finance": "keuangan", "financials": "keuangan", "financial": "keuangan",
#     "tech": "teknologi", "technology": "teknologi", "science": "teknologi",
#     "tech & science": "teknologi",
#     "culture": "budaya", "entertainment": "budaya",
#     "climate": "cuaca", "weather": "cuaca",
# }

# CAT_RULES = [
#     ("crypto", ["btc", "bitcoin", "eth", "ethereum", "solana", "doge", "crypto", "xrp",
#                 "bnb", "avax", "ltc", "ada ", "up or down", "kxcrypto", "kxbtc", "kxeth"]),
#     ("politik", ["president", "election", "senate", "governor", "congress", "prime minister",
#                  "mayor", "democratic", "republican", "trump", "kxelec", "kxpol"]),
#     ("geopolitik", ["war", "ceasefire", "troops", "sanctions", "nuclear", "strait of hormuz",
#                     "ukraine", "russia", "china", "taiwan", "iran", "israel", "gaza"]),
#     ("olahraga", ["nba", "nfl", "mlb", "nhl", "football", "soccer", "tennis", "ufc",
#                   "olympic", "world cup", "lakers", "real madrid", "kxsports"]),
#     ("esports", ["esports", "league of legends", "dota", "cs2", "valorant", "fnatic",
#                  "lck", "lpl", "worlds", "dplus", "t1 "]),
#     ("ekonomi", ["inflation", "cpi", "gdp", "fomc", "rate cut", "interest rate",
#                  "unemployment", "kxecon", "kxcpi", "kxfed"]),
#     ("keuangan", ["s&p", "nasdaq", "dow jones", "stock", "ipo", "spacex", "tesla",
#                   "apple", "kxfin"]),
#     ("teknologi", ["openai", "iphone", "starlink", "artificial intelligence", "kxtech"]),
#     ("budaya", ["oscar", "grammy", "movie", "album", "kxculture"]),
#     ("cuaca", ["hurricane", "temperature", "weather", "tornado", "kxclim"]),
# ]
# def norm(native):
#     """Map kategori native exchange ke kosakata seragam."""
#     if isinstance(native, list):
#         for n in native:
#             c = NATIVE_MAP.get((n or "").strip().lower())
#             if c:
#                 return c
#         return None
#     return NATIVE_MAP.get((native or "").strip().lower())

# # def classify(title: str, ticker: str = "") -> str:
# #     t = (title + " " + (ticker or "")).lower()
# #     for cat, kws in CAT_RULES:
# #         if any(k in t for k in kws):
# #             return cat
# #     return "lainnya"

# def classify(title: str, ticker: str = "") -> str:
#     t = (title + " " + (ticker or "")).lower()
#     for cat, kws in CAT_RULES:
#         if any(k in t for k in kws):
#             return cat
#     return "lainnya"

# # def venue_categories(venue: str, creds: dict):
# #     """Menu pair: top-10 kategori (tanpa 'lainnya'), urut volume 24j (populer)."""
# #     try:
# #         rows = FETCH[venue](creds or {})
# #     except Exception:
# #         return []
# #     agg = {}
# #     for r in rows:
# #         c = classify(r["title"], r["key"])
# #         if c == "lainnya":
# #             continue
# #         a = agg.setdefault(c, {"count": 0, "vol": 0.0})
# #         a["count"] += 1
# #         a["vol"] += r["vol"]
# #     cats = [{"name": k, "count": v["count"], "vol": v["vol"]}
# #             for k, v in agg.items()]
# #     cats.sort(key=lambda x: x["vol"], reverse=True)   # paling populer dulu
# #     return cats[:10]                                  # maks 10 menu

# def venue_categories(venue: str, creds: dict):
#     try:
#         rows = FETCH[venue](creds or {})
#     except Exception:
#         return []
#     agg = {}
#     for r in rows:
#         c = r["cat"]
#         if not c or c == "lainnya":
#             continue
#         a = agg.setdefault(c, {"count": 0, "vol": 0.0})
#         a["count"] += 1
#         a["vol"] += r["vol"]
#     cats = [{"name": k, "count": v["count"], "vol": v["vol"]} for k, v in agg.items()]
#     cats.sort(key=lambda x: x["vol"], reverse=True)
#     return cats[:10]

# def _cat_kalshi(ticker: str) -> str:
#     t = (ticker or "").upper()
#     if t.startswith("KXCRYPTO") or "BTC" in t or "ETH" in t:
#         return "crypto"
#     if t.startswith("KXECON"):
#         return "ekonomi"
#     if "ELECT" in t or "POL" in t:
#         return "politik"
#     return "lainnya"


# # def _poly(creds):
# #     r = httpx.get("https://gamma-api.polymarket.com/markets", params={
# #         "closed": "false", "limit": 30,
# #         "order": "volume24hr", "ascending": "false"}, timeout=15)
# #     return [{
# #         "key": m.get("conditionId") or str(m.get("id")),
# #         "title": (m.get("question") or "?")[:70],
# #         "cat": m.get("category") or "lainnya",
# #         "vol": float(m.get("volume24hr") or 0),
# #         "liq": float(m.get("liquidity") or 0),
# #     } for m in r.json()]

# def _poly(creds):
#     r = httpx.get("https://gamma-api.polymarket.com/markets", params={
#         "closed": "false", "limit": 200,
#         "order": "volume24hr", "ascending": "false"}, timeout=20)
#     return [{
#         "key": m.get("conditionId") or str(m.get("id")),
#         "title": (m.get("question") or "?")[:70],
#         "cat": norm(m.get("category")) or classify(m.get("question") or ""),
#         "vol": float(m.get("volume24hr") or m.get("volumeNum") or 0),
#         "liq": float(m.get("liquidity") or 0),
#     } for m in r.json()]

# # def _kalshi(creds):
# #     base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
# #     r = httpx.get(base + "/trade-api/v2/markets",
# #                   params={"limit": 100, "status": "open"}, timeout=15)
# #     return [{
# #         "key": m.get("ticker"),
# #         "title": (m.get("title") or m.get("subtitle") or "?")[:70],
# #         "cat": _cat_kalshi(m.get("ticker")),
# #         "vol": float(m.get("volume") or 0),
# #         "liq": float(m.get("liquidity") or 0),
# #     } for m in r.json().get("markets", [])]

# def _kalshi(creds):
#     base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
#     r = httpx.get(base + "/trade-api/v2/markets",
#                   params={"limit": 500, "status": "open"}, timeout=20)
#     if r.status_code != 200:
#         r = httpx.get(base + "/trade-api/v2/markets",
#                       params={"limit": 200, "status": "open"}, timeout=20)
#     rows = []
#     for m in r.json().get("markets", []):
#         title = m.get("title") or m.get("subtitle") or ""
#         ser = m.get("series_ticker") or m.get("ticker") or ""
#         rows.append({
#             "key": m.get("ticker"),
#             "title": title[:70],
#             "cat": norm(m.get("category")) or classify(title, ser),
#             "vol": float(m.get("volume_24h") or m.get("volume24h") or m.get("volume") or 0),
#             "liq": float(m.get("liquidity") or 0),
#         })
#     return rows

# # def _limitless(creds):
# #     r = httpx.get("https://api.limitless.exchange/markets/active",
# #                   params={"limit": 25}, timeout=15)
# #     return [{
# #         "key": m.get("slug"),
# #         "title": (m.get("title") or "?")[:70],
# #         "cat": (m.get("categories") or ["lainnya"])[0],
# #         "vol": float(m.get("volumeFormatted") or 0),
# #         "liq": float(m.get("liquidityFormatted") or 0),
# #     } for m in r.json().get("data", [])]

# def _limitless(creds):
#     rows = []
#     for page in (1, 2, 3, 4):                      # 4×25 = ±100 market
#         r = httpx.get("https://api.limitless.exchange/markets/active",
#                       params={"limit": 25, "page": page}, timeout=15)
#         data = r.json().get("data", [])
#         if not data:
#             break
#         for m in data:
#             title = m.get("title") or "?"
#             rows.append({
#                 "key": m.get("slug"),
#                 "title": title[:70],
#                 "cat": norm(m.get("categories")) or classify(title, m.get("slug") or ""),
#                 "vol": float(m.get("volumeFormatted") or 0),
#                 "liq": float(m.get("liquidityFormatted") or 0),
#             })
#     return rows

# FETCH = {"polymarket": _poly, "kalshi": _kalshi, "limitless": _limitless}


# def top_markets(venue: str, creds: dict):
#     try:
#         rows = FETCH[venue](creds or {})
#     except Exception:
#         return {"populer": [], "aktif": []}
#     populer = sorted(rows, key=lambda x: x["vol"], reverse=True)[:5]
#     keys = {p["key"] for p in populer}
#     aktif = sorted([r for r in rows if r["key"] not in keys],
#                    key=lambda x: x["liq"], reverse=True)[:5]
#     return {"populer": populer, "aktif": aktif}