"""Executor S-Final: order real mikro per venue."""
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
# import httpx
import uuid as _uuid
import httpx
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from eth_account import Account

from datetime import datetime, timezone
from eth_account import Account

EXEC_LOG = Path("data") / "exec_log.jsonl"
APPROVED_FLAG = Path("data") / "lim_approved.json"

# EXEC_LOG = Path("data") / "exec_log.jsonl"

SERIES_CANDIDATES = ["KXMLB", "KXNFL", "KXNBA", "KXNHL", "KXELEC", "KXPOL",
                     "KXCPI", "KXFED", "KXBTC", "KXETH", "KXSPX", "KXGOLD"]

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71bF37bb0B8BD"
RPC_BASE = "https://mainnet.base.org"
APPROVED_FLAG = Path("data") / "lim_approved.json"


KALSHI_HOST = "https://external-api.kalshi.com"
KALSHI_ROOT = "/trade-api/v2"


def _k_sign(pem, ts, method, path, body=""):
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    sig = key.sign(f"{ts}{method}{path}{body}".encode(),
                   padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                               salt_length=padding.PSS.DIGEST_LENGTH),
                   hashes.SHA256())
    return base64.b64encode(sig).decode()


def _k_headers(creds, method, path, body=""):
    ts = str(int(time.time() * 1000))
    return {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
            "KALSHI-ACCESS-SIGNATURE": _k_sign(
                creds.get("private_key_pem", ""), ts, method, path, body),
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"}


# def _k_market():
#     with httpx.Client(timeout=10) as client:
#         r = client.get(KALSHI_HOST + KALSHI_ROOT + "/markets",
#                        params={"status": "open", "limit": 100})
#         r.raise_for_status()
#     for m in r.json().get("markets", []):
#         yes = float(m.get("yes_ask") or 0) / 100
#         if 0.30 <= yes <= 0.70 and m.get("ticker"):
#             return {"ticker": m["ticker"], "yes": yes}
#     return None

def _k_price(m):
    for f in ("yes_ask_dollars", "last_price_dollars", "yes_bid_dollars",
              "yes_ask", "last_price", "yes_bid"):
        v = m.get(f)
        if v not in (None, "", 0, "0"):
            v = float(v)
            return v / 100 if v > 1 else v
    return 0.0

def _k_get_market(creds, ticker):
    path = KALSHI_ROOT + "/markets/" + ticker
    for host, hdr in ((KALSHI_HOST, _k_headers(creds, "GET", path)),
                      ("https://api.elections.kalshi.com", None)):
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(host + path, headers=hdr)
                r.raise_for_status()
            m = r.json().get("market") or {}
            if m.get("ticker"):
                return {"ticker": m["ticker"], "yes": _k_price(m) or 0.50}
        except Exception:
            continue
    return None

def _k_market(creds, ticker=None):
    if ticker:
        return _k_get_market(creds, ticker)      # ← endpoint tunggal, terbukti 200
    for host, hdr in ((KALSHI_HOST, _k_headers(creds, "GET", KALSHI_ROOT + "/markets")),
                      ("https://api.elections.kalshi.com", None)):
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(host + KALSHI_ROOT + "/markets",
                               params={"status": "open", "limit": 500}, headers=hdr)
                r.raise_for_status()
            for m in r.json().get("markets", []):
                yes = _k_price(m)
                if 0.30 <= yes <= 0.70 and m.get("ticker"):
                    return {"ticker": m["ticker"], "yes": yes}
        except Exception:
            continue
    return None

def _rpc(method, params=None):
    r = httpx.post(RPC_BASE, json={"jsonrpc": "2.0", "id": 1,
                   "method": method, "params": params or []}, timeout=15)
    return r.json().get("result")


# def _lim_hmac(creds, method, path):
#     ts = datetime.now(timezone.utc).isoformat()
#     msg = f"{ts}\n{method}\n{path}\n"
#     sig = base64.b64encode(hmac.new(base64.b64decode(creds["api_secret"]),
#                    msg.encode(), hashlib.sha256).digest()).decode()
#     return {"lmts-api-key": creds["api_key"],
#             "lmts-timestamp": ts, "lmts-signature": sig}

def _lim_hmac(creds, method, path, body=None):
    ts = datetime.now(timezone.utc).isoformat()
    if body:
        msg = f"{ts}\n{method}\n{path}\n{body}"
    else:
        msg = f"{ts}\n{method}\n{path}\n"
    sig = base64.b64encode(hmac.new(base64.b64decode(creds["api_secret"]),
                   msg.encode(), hashlib.sha256).digest()).decode()
    return {"lmts-api-key": creds["api_key"],
            "lmts-timestamp": ts, "lmts-signature": sig,
            "Content-Type": "application/json"}

# def _lim_switch_eoa(creds):
#     r = httpx.put("https://api.limitless.exchange/profiles",
#                   json={"tradeWalletOption": "eoa"},
#                   headers=_lim_hmac(creds, "PUT", "/profiles"), timeout=15)
#     return r.status_code

def _lim_switch_eoa(creds):
    body = json.dumps({"tradeWalletOption": "eoa"}, separators=(",", ":"))
    r = httpx.put("https://api.limitless.exchange/profiles",
                  content=body,
                  headers=_lim_hmac(creds, "PUT", "/profiles", body), timeout=15)
    return r.status_code

def _lim_approve(pk, spender):
    acct = Account.from_key(pk)
    nonce = int(_rpc("eth_getTransactionCount", [acct.address, "latest"]), 16)
    gp = int(_rpc("eth_gasPrice"), 16)
    data = ("095ea7b3" + spender[2:].rjust(64, "0")
            + format(2**256 - 1, "x").rjust(64, "0"))
    tx = {"chainId": 8453, "nonce": nonce, "to": USDC_BASE,
          "data": "0x" + data, "gas": 120000, "gasPrice": gp * 2}
    signed = Account.sign_transaction(tx, pk)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    return _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])


# def exec_limitless(creds, usd=2, dry=False, ticker=None):
#     pk = creds.get("wallet_pk", "")
#     if not pk:
#         return False, ("Limitless: isi Wallet Private Key dedicated di /setup "
#                        "(mode eoa, tanpa approval partner)")
#     # _lim_switch_eoa(creds)
    
#     r = httpx.get("https://api.limitless.exchange/markets/active",

def exec_limitless(creds, usd=2, dry=False, ticker=None):
    pk = (creds.get("wallet_pk") or "").strip()
    pk_hex = pk[2:] if pk.lower().startswith("0x") else pk
    if len(pk_hex) != 64 or not set(pk_hex) <= set("0123456789abcdefABCDEF"):
        return (False, f"Limitless: field Wallet Private Key berisi "
                       f"{len(pk_hex)} hex (ALAMAT wallet) — butuh PRIVATE KEY "
                       f"64 hex; minta re-ekspor dari wallet")
    # _lim_switch_eoa(creds)   # ← BIARKAN DIKOMENTAR (sudah Anda lakukan)
    r = httpx.get("https://api.limitless.exchange/markets/active",
                  params={"limit": 25}, timeout=15)
    m = next((x for x in r.json().get("data", [])
              if x.get("prices") and len(x["prices"]) == 2), None)
    if not m:
        return False, "tidak ada market limitless"
    d = httpx.get(f"https://api.limitless.exchange/markets/{m['slug']}",
                  timeout=15).json().get("data", {})
    exchange = (d.get("venue") or {}).get("exchange") or d.get("exchangeAddress")
    token_id = int((d.get("tokenIds") or [0])[0] or d.get("yesTokenId") or 0)
    
    pk = (creds.get("wallet_pk") or "").strip()
    pk_hex = pk[2:] if pk.lower().startswith("0x") else pk
    if len(pk_hex) != 64 or not set(pk_hex) <= set("0123456789abcdefABCDEF"):
        return (False, f"Limitless: field Wallet Private Key berisi "
                       f"{len(pk_hex)} hex (ALAMAT wallet) — butuh PRIVATE KEY "
                       f"64 hex; minta re-ekspor dari wallet")
        
    acct = Account.from_key(pk)
    if not APPROVED_FLAG.exists():
        _lim_approve(pk, exchange)
        APPROVED_FLAG.write_text(json.dumps({"ts": time.time()}))
    maker_amount = int(usd * 1e6)
    order = {"salt": int(time.time() * 1000), "maker": acct.address,
             "signer": acct.address,
             "taker": "0x0000000000000000000000000000000000000000",
             "tokenId": token_id, "makerAmount": maker_amount,
             "takerAmount": 1, "expiration": 0, "nonce": 0,
             "feeRateBps": 0, "side": 0, "signatureType": 0}
    domain = {"name": "Limitless CTF Exchange", "version": "1",
              "chainId": 8453, "verifyingContract": exchange}
    types = {"Order": [
        {"name": "salt", "type": "uint256"}, {"name": "maker", "type": "address"},
        {"name": "signer", "type": "address"}, {"name": "taker", "type": "address"},
        {"name": "tokenId", "type": "uint256"},
        {"name": "makerAmount", "type": "uint256"},
        {"name": "takerAmount", "type": "uint256"},
        {"name": "expiration", "type": "uint256"}, {"name": "nonce", "type": "uint256"},
        {"name": "feeRateBps", "type": "uint256"}, {"name": "side", "type": "uint8"},
        {"name": "signatureType", "type": "uint8"}]}
    sig = Account.sign_typed_data(pk, domain, types, order)
    if dry:
        return True, f"[DRY] limitless BUY {m['title'][:40]} sig={sig.signature.hex()[:20]}…"
    # ro = httpx.post("https://api.limitless.exchange/orders",
    #                 json={**order, "signature": sig.signature.hex(),
    #                       "market": m["slug"]},
    #                 headers=_lim_hmac(creds, "POST", "/orders"), timeout=15)

    order_payload = {**order, "signature": sig.signature.hex(),
                     "market": m["slug"]}
    order_body = json.dumps(order_payload, separators=(",", ":"))
    ro = httpx.post("https://api.limitless.exchange/orders",
                    content=order_body,
                    headers=_lim_hmac(creds, "POST", "/orders", order_body),
                    timeout=15)
    
    _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "venue": "limitless",
          "status": ro.status_code, "body": ro.text[:150]})
    if ro.status_code in (200, 201):
        return True, f"BUY {usd} USDC :: {m['title'][:40]}"
    return False, f"limitless {ro.status_code}: {ro.text[:120]}"

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

def exec_polymarket(creds, usd=2, dry=False, ticker=None):
    m = _poly_market()
    if not m:
        return False, "tidak ada market likuid"
    price = min(round(m["ask"] + 0.01, 2), 0.99)
    size = max(1, int(usd // price))
    if dry:
        return True, f"[DRY] BUY YES {size} x {price} :: {m['q'][:50]}"
    # ---- GUARDRAIL: order real wajib proxy (deposit wallet flow) ----
    if not dry and not creds.get("proxy_address"):                      # ← TAMBAH
        return (False, "Poly real butuh Deposit/Proxy Wallet Address — "
                       "isi di /setup (deposit wallet flow wajib)")     # ← TAMBAH
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
            client_args["signature_type"] = 2     # POLY_PROXY — workaround resmi            
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
#     re_ = httpx.get(base + "/trade-api/v2/events",
#                     params={"limit": 100, "status": "open"}, timeout=15)
#     evs = sorted([e for e in re_.json().get("events", [])
#                   if not (e.get("ticker") or "").startswith("KXMVE")],
#                  key=lambda e: float(e.get("volume") or 0), reverse=True)
#     for ev in evs[:10]:
#         rm = httpx.get(base + "/trade-api/v2/markets",
#                        params={"event_ticker": ev.get("ticker"),
#                                "status": "open"}, timeout=12)
#         for m in rm.json().get("markets", []):
#             ask = float(m.get("yes_ask_dollars") or 0)
#             if 0.05 < ask < 0.95:
#                 return {"t": m["ticker"], "ask": ask,
#                         "q": m.get("title") or ev.get("ticker")}
#     return None

# def _kalshi_market(base):
#     def get(params):
#         try:
#             r = httpx.get(base + "/trade-api/v2/markets",
#                           params=params, timeout=15)
#             return r.json() if r.status_code == 200 else None
#         except Exception:
#             return None

#     pages = []
#     j = get({"limit": 500, "status": "open", "order_by": "volume"})
#     if j is None:                                   # server tak kenal order_by
#         j = get({"limit": 500, "status": "open"})
#     while j and len(pages) < 6:                     # maks ±3.000 market
#         pages.append(j)
#         cur = j.get("cursor")
#         if not cur:
#             break
#         j = get({"limit": 500, "status": "open", "cursor": cur})

#     best = None
#     for pg in pages:
#         for m in pg.get("markets", []):
#             t = m.get("ticker") or ""
#             if t.startswith("KXMVE"):
#                 continue
#             ask = float(m.get("yes_ask_dollars") or 0)
#             vol = float(m.get("volume_fp") or 0)
#             if 0.05 < ask < 0.95 and (best is None or vol > best["vol"]):
#                 best = {"t": t, "ask": ask, "vol": vol,
#                         "q": m.get("title") or t}
#         if best and best["vol"] > 0:
#             break
#     return best

def _kalshi_market(base):
    best = None
    for ser in SERIES_CANDIDATES:
        try:
            r = httpx.get(base + "/trade-api/v2/markets",
                          params={"limit": 50, "status": "open",
                                  "series_ticker": ser}, timeout=12)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        for m in r.json().get("markets", []):
            t = m.get("ticker") or ""
            if t.startswith("KXMVE"):
                continue
            ask = float(m.get("yes_ask_dollars") or 0)
            vol = float(m.get("volume_fp") or 0)
            if 0.05 < ask < 0.95 and (best is None or vol > best["vol"]):
                best = {"t": t, "ask": ask, "vol": vol, "q": m.get("title") or t}
        if best and best["vol"] > 0:
            break
    return best

# def exec_kalshi(creds, usd=2, dry=False, ticker=None):
#     # m = _k_market()
#     m = _k_market(creds, ticker=ticker)     # ← ganti baris lama
#     if not m:
#         return False, "tidak ada market kalshi likuid"
#     price = min(round(m["yes"] + 0.01, 2), 0.99)
#     size = max(1, int(usd // price))
#     if dry:
#         return True, f"[DRY] kalshi BUY YES {size} x {price} :: {m['ticker']}"
#     # path = KALSHI_ROOT + "/portfolio/events/orders"
#     # body = json.dumps({
#     #     "ticker": m["ticker"],
#     #     "side": "bid",
#     #     "count": f"{size:.2f}",
#     #     "price": f"{price:.4f}",
#     #     "client_order_id": str(_uuid.uuid4()),
#     # }, separators=(",", ":"))
#     # log = []
#     # for host in (KALSHI_HOST, "https://api.elections.kalshi.com"):
#     #     for variant_name, payload_fn in [
#     #         ("A:ts+method+path", lambda t: f"{t}POST{path}"),
#     #         ("B:ts+method+path+body", lambda t: f"{t}POST{path}{body}"),
#     #         ("C:method+path+body+ts", lambda t: f"POST{path}{body}{t}"),
#     #         ("D:method+path+ts", lambda t: f"POST{path}{t}"),
#     #     ]:
#     #         ts = str(int(time.time() * 1000))
#     #         key = serialization.load_pem_private_key(creds.get("private_key_pem", "").encode(), password=None)
#     #         sig = base64.b64encode(key.sign(payload_fn(ts).encode(),
#     #             padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
#     #                         salt_length=padding.PSS.DIGEST_LENGTH),
#     #             hashes.SHA256())).decode()
#     #         hdrs = {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
#     #                 "KALSHI-ACCESS-SIGNATURE": sig,
#     #                 "KALSHI-ACCESS-TIMESTAMP": ts,
#     #                 "Content-Type": "application/json"}
#     #         with httpx.Client(timeout=15) as client:
#     #             r = client.post(host + path, headers=hdrs, content=body)
#     #         tag = f"[{host.split('://')[1]}|{variant_name}]"
#     #         log.append(f"{tag} {r.status_code}")
#     #         if r.status_code < 400:
#     #             return True, f"BUY YES {size} x {price} :: {m['ticker']}"
#     # return False, "kalshi: " + " | ".join(log)

#     path = KALSHI_ROOT + "/portfolio/events/orders"
#     body = json.dumps({
#         "ticker": m["ticker"],
#         "side": "bid",
#         "count": f"{size:.2f}",
#         "price": f"{price:.4f}",
#         "client_order_id": str(_uuid.uuid4()),
#     }, separators=(",", ":"))

#     body_hash = hashlib.sha256(body.encode()).hexdigest()
#     log = []

#     for host in (KALSHI_HOST, "https://api.elections.kalshi.com"):
#         for variant_name, payload_fn in [
#             ("A:ts+method+path", lambda t: f"{t}POST{path}"),
#             ("B:ts+method+path+body", lambda t: f"{t}POST{path}{body}"),
#             ("C:ts+method+path+hash", lambda t: f"{t}POST{path}{body_hash}"),
#             ("D:method+path+hash+ts", lambda t: f"POST{path}{body_hash}{t}"),
#         ]:
#             ts = str(int(time.time() * 1000))
#             key = serialization.load_pem_private_key(creds.get("private_key_pem", "").encode(), password=None)
#             sig = base64.b64encode(key.sign(payload_fn(ts).encode(),
#                 padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
#                             salt_length=padding.PSS.DIGEST_LENGTH),
#                 hashes.SHA256())).decode()
#             hdrs = {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
#                     "KALSHI-ACCESS-SIGNATURE": sig,
#                     "KALSHI-ACCESS-TIMESTAMP": ts,
#                     "Content-Type": "application/json"}
#             with httpx.Client(timeout=15) as client:
#                 r = client.post(host + path, headers=hdrs, content=body)
#             tag = f"[{host.split('://')[1]}|{variant_name}]"
#             log.append(f"{tag} {r.status_code}")
#             if r.status_code < 400:
#                 return True, f"BUY YES {size} x {price} :: {m['ticker']}"
#     return False, "kalshi: " + " | ".join(log)
#     return True, f"BUY YES {size} x {price} :: {m['ticker']}"

def exec_kalshi(creds, usd=2, dry=False, ticker=None):
    m = _k_market(creds, ticker=ticker)
    if not m:
        return False, "tidak ada market kalshi likuid"
    price = min(round(m["yes"] + 0.01, 2), 0.99)
    size = max(1, int(usd // price))
    if dry:
        return True, f"[DRY] kalshi BUY YES {size} x {price} :: {m['ticker']}"
    path = KALSHI_ROOT + "/portfolio/events/orders"
    body = json.dumps({
        "ticker": m["ticker"],
        "side": "bid",
        "count": f"{size:.2f}",
        "price": f"{price:.4f}",
        "client_order_id": str(_uuid.uuid4()),
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
    }, separators=(",", ":"))
    ts = str(int(time.time() * 1000))
    key = serialization.load_pem_private_key(
        creds.get("private_key_pem", "").encode(), password=None)
    sig = base64.b64encode(key.sign(f"{ts}POST{path}".encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256())).decode()
    hdrs = {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"}
    with httpx.Client(timeout=15) as client:
        r = client.post(KALSHI_HOST + path, headers=hdrs, content=body)
    if r.status_code >= 400:
        return False, f"kalshi {r.status_code}: {r.text[:200]}"
    return True, f"BUY YES {size} x {price} :: {m['ticker']}"

# def exec_limitless(creds, usd=1, dry=False):
#     return False, ("Limitless read-only: order butuh tanda tangan EIP-712 "
#                    "wallet / delegated partner (di luar scope fase ini)")


EXEC = {"polymarket": exec_polymarket, "kalshi": exec_kalshi,
        "limitless": exec_limitless}