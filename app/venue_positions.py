"""Open positions per venue — data real dari exchange."""
import base64
import hashlib
import hmac
import httpx
import time
from datetime import datetime, timezone


def _poly(creds):
    from eth_account import Account
    pk = creds.get("private_key", "")
    if not pk:
        return []
    addr = Account.from_key(pk).address
    r = httpx.get("https://data-api.polymarket.com/positions",
                  params={"user": addr, "limit": 20}, timeout=15)
    return [{"title": (p.get("title") or p.get("market") or "?")[:60],
             "size": round(float(p.get("size") or 0), 2),
             "value": round(float(p.get("curValue") or p.get("value") or 0), 2)}
            for p in r.json() if float(p.get("size") or 0) > 0]


def _kalshi(creds):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key_id = creds.get("api_key_id", "")
    pem = (creds.get("private_key_pem") or "").strip()
    if not key_id or "-----BEGIN" not in pem:
        return []
    base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
    ts = str(int(time.time() * 1000))
    path = "/trade-api/v2/portfolio/positions"
    msg = f"{ts}GET{path}".encode()
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                   salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
    r = httpx.get(base + path, headers={
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
    return [{"title": (p.get("market_ticker") or p.get("ticker") or "?")[:60],
             "size": float(p.get("quantity") or p.get("position") or 0),
             "value": round(float(p.get("market_value") or 0), 2)}
            for p in r.json().get("positions", [])]


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


GETPOS = {"polymarket": _poly, "kalshi": _kalshi, "limitless": _limitless}


def get_positions(venue, creds):
    try:
        return GETPOS[venue](creds or {})
    except Exception:
        return []