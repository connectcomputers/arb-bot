# app/venue_positions.py

"""Open positions per venue — data real dari exchange."""
import base64
import hashlib
import hmac
import httpx
import time
from datetime import datetime, timezone


def _poly(creds):
    from eth_account import Account
    from app.proxy_util import poly_proxy
    pk = creds.get("private_key", "")
    if not pk:
        return []
    # addr = Account.from_key(pk).address

    # addr = (creds.get("proxy_address") or "").strip() or Account.from_key(pk).address

    from app.config_store import get_poly_funder
    addr = get_poly_funder() or Account.from_key(pk).address
    
    with poly_proxy(creds.get("proxy_url")):
        r = httpx.get("https://data-api.polymarket.com/positions",
                      params={"user": addr, "limit": 20}, timeout=15)
    return [{"title": (p.get("title") or p.get("market") or "?")[:60],
             "size": round(float(p.get("size") or 0), 2),
            #  "value": round(float(p.get("curValue") or p.get("value") or 0), 2)}

             "value": round(next((float(p[k]) for k in
                      ("curValue", "currentValue", "usdcValue", "marketValue", "value")
                      if float(p.get(k) or 0) > 0),
                      float(p.get("size") or 0) *
                      float(p.get("curPrice") or p.get("price") or 0)), 2)}
                      
            for p in r.json() if float(p.get("size") or 0) > 0]


def _kalshi(creds):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key_id = creds.get("api_key_id", "")
    pem = (creds.get("private_key_pem") or "").strip()
    if not key_id or "-----BEGIN" not in pem:
        return []
    base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
    rows = []
    for path in ("/trade-api/v2/portfolio/positions",
                 "/trade-api/v2/positions",
                 "/trade-api/v2/portfolio/positions?exchange_index=0",
                 "/trade-api/v2/portfolio/positions?exchange_index=1"):
        try:
            ts = str(int(time.time() * 1000))
            signpath = path.split("?")[0]
            msg = f"{ts}GET{signpath}".encode()
            key = serialization.load_pem_private_key(pem.encode(), password=None)
            sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                           salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
            r = httpx.get(base + path, headers={
                "KALSHI-ACCESS-KEY": key_id,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
                "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
            if r.status_code != 200:
                continue
            d = r.json()
            cand = (d.get("positions") or d.get("market_positions") or
                    (d.get("data") or {}).get("positions") or [])
            if cand:
                rows = cand
                break
        except Exception:
            continue
    out = []
    for p in rows:
        qty = float(p.get("quantity") or p.get("position") or 0)
        if qty == 0:
            continue
        cost = round(float(p.get("total_cost") or 0), 2)
        pnl = round(float(p.get("unrealized_pnl") or p.get("total_pnl") or 0), 2)
        out.append({"title": (p.get("market_ticker") or p.get("ticker") or
                    p.get("event_ticker") or "?")[:60],
                    "size": qty,
                    "value": round(float(p.get("market_value") or 0), 2),
                    "cost": cost,
                    "pnl": pnl,
                    "pnl_pct": round(pnl / cost * 100, 2) if cost else 0.0})
    return out


def _limitless(creds):
    key = creds.get("api_key", "")
    secret = creds.get("api_secret", "")
    if not key or not secret:
        return []
    ts = datetime.now(timezone.utc).isoformat()
    path = "/portfolio/positions"
    message = f"{ts}\nGET\n{path}\n"
    sig = base64.b64encode(hmac.new(base64.b64decode(secret),
                   message.encode(), hashlib.sha256).digest()).decode()
    r = httpx.get("https://api.limitless.exchange" + path, headers={
        "lmts-api-key": key, "lmts-timestamp": ts,
        "lmts-signature": sig}, timeout=15)
    d = r.json()
    rows = d.get("data") or d.get("positions") or []
    return [{"title": (p.get("title") or p.get("market") or "?")[:60],
             "size": float(p.get("size") or p.get("quantity") or 0),
             "value": round(float(p.get("value") or p.get("curValue") or 0), 2)}
            for p in rows]




def _poly_detailed(creds):
    """Polymarket positions dengan metadata lengkap untuk SELL."""
    from eth_account import Account
    from app.proxy_util import poly_proxy
    pk = creds.get("private_key", "")
    if not pk:
        return []
    from app.config_store import get_poly_funder
    addr = get_poly_funder() or Account.from_key(pk).address
    with poly_proxy(creds.get("proxy_url")):
        r = httpx.get("https://data-api.polymarket.com/positions",
                      params={"user": addr, "limit": 50}, timeout=15)
    return [{"title": (p.get("title") or p.get("market") or "?")[:60],
             "size": round(float(p.get("size") or 0), 2),
             "value": round(next((float(p[k]) for k in
                      ("curValue", "currentValue", "usdcValue", "marketValue", "value")
                      if float(p.get(k) or 0) > 0),
                      float(p.get("size") or 0) * float(p.get("curPrice") or p.get("price") or 0)), 2),
             "condition_id": p.get("conditionId") or p.get("condition_id"),
             "token_id": p.get("tokenId") or p.get("token_id") or p.get("asset"),
             "outcome": (p.get("outcome") or "YES").upper(), "cur_price": float(p.get("curPrice") or p.get("price") or 0), "pnl": round(float(p.get("cashPnl") or 0), 2), "pnl_pct": round(float(p.get("percentPnl") or 0), 2)}
            for p in r.json() if float(p.get("size") or 0) > 0]

def _kalshi_detailed(creds):
    rows = _kalshi(creds)
    for r in rows:
        r.setdefault("ticker", r.get("title"))
        r.setdefault("side", "yes")
    return rows


def _limitless_detailed(creds):
    """Limitless positions dengan market identifier."""
    key = creds.get("api_key", "")
    secret = creds.get("api_secret", "")
    if not key or not secret:
        return []
    ts = datetime.now(timezone.utc).isoformat()
    path = "/portfolio/positions"
    message = f"{ts}\nGET\n{path}\n"
    sig = base64.b64encode(hmac.new(base64.b64decode(secret),
                   message.encode(), hashlib.sha256).digest()).decode()
    r = httpx.get("https://api.limitless.exchange" + path, headers={
        "lmts-api-key": key, "lmts-timestamp": ts,
        "lmts-signature": sig}, timeout=15)
    d = r.json()
    rows = d.get("data") or d.get("positions") or []
    return [{"title": (p.get("title") or p.get("market") or "?")[:60],
             "market_slug": p.get("slug") or p.get("market_slug") or p.get("marketId"),
             "size": float(p.get("size") or p.get("quantity") or 0),
             "value": round(float(p.get("value") or p.get("curValue") or 0), 2)}
            for p in rows]

def get_positions_detailed(venue, creds):
    """Positions dengan metadata lengkap untuk auto-TP dan SELL."""
    try:
        if venue == "polymarket":
            return _poly_detailed(creds or {})
        elif venue == "kalshi":
            return _kalshi_detailed(creds or {})
        elif venue == "limitless":
            return _limitless_detailed(creds or {})
        return []
    except Exception:
        return []
GETPOS = {"polymarket": _poly, "kalshi": _kalshi, "limitless": _limitless}


def get_positions(venue, creds):
    try:
        return GETPOS[venue](creds or {})
    except Exception:
        return []

# ==========================================================================================================
# """Open positions per venue — data real dari exchange."""
# import base64
# import hashlib
# import hmac
# import httpx
# import time
# from datetime import datetime, timezone


# def _poly(creds):
#     from eth_account import Account
#     pk = creds.get("private_key", "")
#     if not pk:
#         return []
#     addr = Account.from_key(pk).address
#     r = httpx.get("https://data-api.polymarket.com/positions",
#                   params={"user": addr, "limit": 20}, timeout=15)
#     return [{"title": (p.get("title") or p.get("market") or "?")[:60],
#              "size": round(float(p.get("size") or 0), 2),
#              "value": round(float(p.get("curValue") or p.get("value") or 0), 2)}
#             for p in r.json() if float(p.get("size") or 0) > 0]


# def _kalshi(creds):
#     from cryptography.hazmat.primitives import hashes, serialization
#     from cryptography.hazmat.primitives.asymmetric import padding
#     key_id = creds.get("api_key_id", "")
#     pem = (creds.get("private_key_pem") or "").strip()
#     if not key_id or "-----BEGIN" not in pem:
#         return []
#     base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
#     ts = str(int(time.time() * 1000))
#     path = "/trade-api/v2/portfolio/positions"
#     msg = f"{ts}GET{path}".encode()
#     key = serialization.load_pem_private_key(pem.encode(), password=None)
#     sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
#                    salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
#     r = httpx.get(base + path, headers={
#         "KALSHI-ACCESS-KEY": key_id,
#         "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
#         "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
#     return [{"title": (p.get("market_ticker") or p.get("ticker") or "?")[:60],
#              "size": float(p.get("quantity") or p.get("position") or 0),
#              "value": round(float(p.get("market_value") or 0), 2)}
#             for p in r.json().get("positions", [])]


# def _limitless(creds):
#     key = creds.get("api_key", "")
#     secret = creds.get("api_secret", "")
#     if not key or not secret:
#         return []
#     ts = datetime.now(timezone.utc).isoformat()
#     path = "/portfolio/positions"
#     message = f"{ts}\nGET\n{path}\n"
#     sig = base64.b64encode(hmac.new(base64.b64decode(secret),
#                    message.encode(), hashlib.sha256).digest()).decode()
#     r = httpx.get("https://api.limitless.exchange" + path, headers={
#         "lmts-api-key": key, "lmts-timestamp": ts,
#         "lmts-signature": sig}, timeout=15)
#     d = r.json()
#     rows = d.get("data") or d.get("positions") or []
#     return [{"title": (p.get("title") or p.get("market") or "?")[:60],
#              "size": float(p.get("size") or p.get("quantity") or 0),
#              "value": round(float(p.get("value") or p.get("curValue") or 0), 2)}
#             for p in rows]


# GETPOS = {"polymarket": _poly, "kalshi": _kalshi, "limitless": _limitless}


# def get_positions(venue, creds):
#     try:
#         return GETPOS[venue](creds or {})
#     except Exception:
#         return []