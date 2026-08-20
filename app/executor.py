"""Executor S-Final: order real mikro per venue."""
import base64
import json
import time
from pathlib import Path

import httpx

EXEC_LOG = Path("data") / "exec_log.jsonl"


def _log(entry: dict):
    EXEC_LOG.parent.mkdir(exist_ok=True)
    with EXEC_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# def _poly_market():
#     r = httpx.get("https://gamma-api.polymarket.com/markets", params={
#         "closed": "false", "limit": 10, "order": "volume24hr",
#         "ascending": "false"}, timeout=10)
#     for m in r.json():
#         ids = m.get("clobTokenIds")
#         ask = float(m.get("bestAsk") or 0)
#         if ids and ask > 0:
#             try:
#                 toks = json.loads(ids)
#             except Exception:
#                 continue
#             return {"q": m.get("question") or "?", "yes": toks[0], "ask": ask}
#     return None

def _poly_market():
    r = httpx.get("https://gamma-api.polymarket.com/markets", params={
        "closed": "false", "limit": 50, "order": "volume24hr",
        "ascending": "false"}, timeout=10)
    for m in r.json():
        ids = m.get("clobTokenIds")
        ask = float(m.get("bestAsk") or 0)
        if ids and 0.25 <= ask <= 0.75:          # posisi wajar, bukan lotre 1¢
            try:
                toks = json.loads(ids)
            except Exception:
                continue
            return {"q": m.get("question") or "?", "yes": toks[0], "ask": ask}
    return None

def exec_polymarket(creds, usd=2, dry=False):
    m = _poly_market()
    if not m:
        return False, "tidak ada market likuid"
    price = min(round(m["ask"] + 0.01, 2), 0.99)
    size = max(1, int(usd // price))
    if dry:
        return True, f"[DRY] BUY YES {size} x {price} :: {m['q'][:50]}"
    try:
        # from py_clob_client_v2 import ClobClient
        # from py_clob_client_v2.clob_types import OrderArgs, OrderType
        # from py_clob_client_v2.order_builder.constants import BUY
        # c = ClobClient(host="https://clob.polymarket.com", chain_id=137,
        #                key=creds.get("private_key", ""))
        # try:
        #     api = c.create_or_derive_api_key()
        # except Exception:
        #     api = c.derive_api_key()
        # if api is not None and hasattr(c, "set_api_creds"):
        #     c.set_api_creds(api)                 # ← kunci: header L2 terpasang
        # order = c.create_order(OrderArgs(token_id=m["yes"], price=price,
        #                                  size=size, side=BUY))
        # resp = c.post_order(order, OrderType.FAK)

        from py_clob_client_v2 import ClobClient
        from py_clob_client_v2.clob_types import OrderArgs, OrderType
        from py_clob_client_v2.order_builder.constants import BUY
        client_args = {
            "host": "https://clob.polymarket.com",
            "chain_id": 137,
            "key": creds.get("private_key", ""),
        }
        proxy = creds.get("proxy_address")
        if proxy:
            client_args["funder"] = proxy          # ← deposit wallet flow
        c = ClobClient(**client_args)
        try:
            api = c.create_or_derive_api_key()
        except Exception:
            api = c.derive_api_key()
        if api is not None and hasattr(c, "set_api_creds"):
            c.set_api_creds(api)
        order = c.create_order(OrderArgs(token_id=m["yes"], price=price,
                                         size=size, side=BUY))
        resp = c.post_order(order, OrderType.FAK)
        
        _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "venue": "polymarket",
              "side": "BUY-YES", "price": price, "size": size,
              "resp": str(resp)[:120]})
        return True, f"BUY YES {size} x {price} :: {m['q'][:40]}"
    except Exception as e:
        return False, f"gagal: {e}"


# def _kalshi_market(base):
#     r = httpx.get(base + "/trade-api/v2/markets",
#                   params={"limit": 200, "status": "open"}, timeout=12)
#     for m in r.json().get("markets", []):
#         if (m.get("ticker") or "").startswith("KXMVE"):
#             continue
#         ask = float(m.get("yes_ask_dollars") or 0)
#         if ask > 0:
#             return {"t": m["ticker"], "ask": ask,
#                     "q": m.get("title") or m["ticker"]}
#     return None

# def _kalshi_market(base):
#     r = None
#     for lim in (1000, 500, 200):
#         r = httpx.get(base + "/trade-api/v2/markets",
#                       params={"limit": lim, "status": "open"}, timeout=15)
#         if r.status_code == 200:
#             break
#     ms = [m for m in r.json().get("markets", [])
#           if not (m.get("ticker") or "").startswith("KXMVE")]
#     best = None
#     for m in ms:
#         ask = float(m.get("yes_ask_dollars") or 0)
#         vol = float(m.get("volume_fp") or 0)
#         if 0.05 < ask < 0.95 and (best is None or vol > best["vol"]):
#             best = {"t": m["ticker"], "ask": ask, "vol": vol,
#                     "q": m.get("title") or m["ticker"]}
#     if best:
#         return best
#     for m in ms:
#         lp = float(m.get("last_price_dollars") or 0)
#         if 0.05 < lp < 0.95:
#             return {"t": m["ticker"], "ask": min(lp + 0.03, 0.99),
#                     "q": m.get("title") or m["ticker"]}
#     return None

def _kalshi_market(base):
    re_ = httpx.get(base + "/trade-api/v2/events",
                    params={"limit": 100, "status": "open"}, timeout=15)
    evs = sorted([e for e in re_.json().get("events", [])
                  if not (e.get("ticker") or "").startswith("KXMVE")],
                 key=lambda e: float(e.get("volume") or 0), reverse=True)
    for ev in evs[:10]:
        rm = httpx.get(base + "/trade-api/v2/markets",
                       params={"event_ticker": ev.get("ticker"),
                               "status": "open"}, timeout=12)
        for m in rm.json().get("markets", []):
            ask = float(m.get("yes_ask_dollars") or 0)
            if 0.05 < ask < 0.95:
                return {"t": m["ticker"], "ask": ask,
                        "q": m.get("title") or ev.get("ticker")}
    return None

def exec_kalshi(creds, usd=2, dry=False):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key_id = creds.get("api_key_id", "")
    pem = (creds.get("private_key_pem") or "").strip()
    if not key_id or "-----BEGIN" not in pem:
        return False, "kredensial kalshi belum lengkap"
    base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
    m = _kalshi_market(base)
    if not m:
        return False, "tidak ada market ber-quote"
    price = min(round(m["ask"] + 0.01, 2), 0.99)
    count = max(1, int(usd))
    body = {"action": "buy", "side": "yes", "ticker": m["t"],
            "count": count, "type": "limit", "price": price}
    if dry:
        return True, f"[DRY] {body}"
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    for path in ("/trade-api/v2/orders", "/trade-api/v2/portfolio/orders",
                 "/portfolio/orders"):
        ts = str(int(time.time() * 1000))
        msg = f"{ts}POST{path}".encode()
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                       salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256)
        r = httpx.post(base + path, json=body, headers={
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=12)
        if r.status_code != 404:
            _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "venue": "kalshi",
                  "path": path, "status": r.status_code, "body": r.text[:150]})
            if r.status_code in (200, 201):
                return True, f"BUY YES {count} x {price} :: {m['q'][:40]}"
            return False, f"kalshi {r.status_code}: {r.text[:120]}"
    return False, "semua path order 404"


def exec_limitless(creds, usd=1, dry=False):
    return False, ("Limitless read-only: order butuh tanda tangan EIP-712 "
                   "wallet / delegated partner (di luar scope fase ini)")


EXEC = {"polymarket": exec_polymarket, "kalshi": exec_kalshi,
        "limitless": exec_limitless}