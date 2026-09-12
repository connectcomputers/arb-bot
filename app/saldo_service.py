# app/saldo_service.py
"""
Service untuk cek saldo semua venue (reusable dari CLI & web).
"""
import base64
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.config_store import load_creds
from app.executor import _lim_hmac
from app.proxy_util import poly_proxyed


def kalshi_get(creds, path):
    key = serialization.load_pem_private_key(
        creds['private_key_pem'].encode(), password=None)
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(key.sign(f'{ts}GET{path}'.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
                    hashes.SHA256())).decode()
    return httpx.get('https://external-api.kalshi.com' + path, headers={
        'KALSHI-ACCESS-KEY': creds['api_key_id'],
        'KALSHI-ACCESS-SIGNATURE': sig,
        'KALSHI-ACCESS-TIMESTAMP': ts}, timeout=10)


def get_saldo_kalshi(c):
    res = {"venue": "kalshi", "status": "unknown"}
    try:
        r = kalshi_get(c, '/trade-api/v2/portfolio/balance')
        if r.status_code == 200:
            d = r.json()
            res["cash_usd"] = float(d.get("balance_dollars", 0))
            res["portfolio_usd"] = int(d.get("portfolio_value", 0)) / 100
            res["status"] = "ok"
        
        r2 = kalshi_get(c, '/trade-api/v2/portfolio/positions')
        if r2.status_code == 200:
            pos = r2.json()
            # res["posisi_market"] = len(pos.get("market_positions", []))
            # res["posisi_event"] = len(pos.get("event_positions", []))

            mp = [p for p in pos.get("market_positions", [])
                  if float(p.get("quantity") or 0) != 0]
            ep = [p for p in pos.get("event_positions", [])
                  if float(p.get("quantity") or p.get("position") or 0) != 0]
            res["posisi_market"] = len(mp)
            res["posisi_event"] = len(ep)

    except Exception as e:
        res["error"] = str(e)
    return res


def get_saldo_limitless(c):
    res = {"venue": "limitless", "status": "unknown"}
    try:
        me = httpx.get("https://api.limitless.exchange/profiles/me",
                       headers=_lim_hmac(c, "GET", "/profiles/me"),
                       timeout=10).json()
        # sw = me.get("smartWallet")
        # res["smart_wallet"] = sw

        sw = me.get("smartWallet")
        if not sw:
            from eth_account import Account
            # for k in ("private_key", "eoa_private_key", "private_key_eoa",
            #           "eoa_key", "wallet_private_key"):

            for k in ("wallet_pk", "private_key", "eoa_private_key",
                      "private_key_eoa", "eoa_key", "wallet_private_key"):
                
                if c.get(k):
                    try:
                        sw = Account.from_key(c[k]).address
                        break
                    except Exception:
                        continue
        if not sw:
            for k in ("eoa_address", "eoa", "wallet_address", "address"):
                if c.get(k):
                    sw = c[k]
                    break
        res["smart_wallet"] = sw
        if not sw:
            res["error"] = "EOA tidak ditemukan; field creds=" + ",".join(sorted(c.keys()))
            return res
                
        USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        data = "0x70a08231" + sw[2:].lower().rjust(64, "0")
        r = httpx.post("https://mainnet.base.org",
                       json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                             "params": [{"to": USDC, "data": data}, "latest"]},
                       timeout=10)
        res["usdc_base"] = int(r.json().get("result") or "0x0", 16) / 1e6
        res["status"] = "ok"
    except Exception as e:
        res["error"] = str(e)
    return res


@poly_proxyed
def get_saldo_polymarket(c):
    from eth_account import Account
    res = {"venue": "polymarket", "status": "unknown"}
    try:
        res["signer"] = Account.from_key(c.get("private_key", "")).address
        res["proxy"] = c.get("proxy_address", "")
        res["geoblock"] = False        
        
        def bal(tok, a):
            data = "0x70a08231" + a[2:].lower().rjust(64, "0")
            r = httpx.post("https://polygon-rpc.com",
                           json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                 "params": [{"to": tok, "data": data}, "latest"]},
                           timeout=10)
            return int(r.json().get("result") or "0x0", 16) / 1e6

        # USDCe = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        # res["usdce_signer"] = bal(USDCe, res["signer"])
        # res["usdce_proxy"] = bal(USDCe, res["proxy"])
        # res["web_usd"] = 19.95  # hardcode dari web (off-chain)
        # res["catatan"] = "saldo web di ledger internal (off-chain)"
        # res["status"] = "ok"

        USDCe = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        res["usdce_signer"] = bal(USDCe, res["signer"])
        res["usdce_proxy"] = bal(USDCe, res["proxy"])

        # Saldo REAL: cash di ledger CLOB + nilai posisi dari data-api
        funder = (c.get("proxy_address") or "").strip()
        cash = None
        try:
            import json as _j
            from pathlib import Path as _P
            from py_clob_client_v2 import ClobClient, ApiCreds
            _cf = _P("data/poly_clob_creds.json")
            if _cf.exists():
                dd = _j.loads(_cf.read_text())
                cl = ClobClient(host="https://clob.polymarket.com", chain_id=137,
                                key=c.get("private_key", ""), funder=funder,
                                signature_type=3,
                                creds=ApiCreds(api_key=dd["api_key"],
                                               api_secret=dd["api_secret"],
                                               api_passphrase=dd["api_passphrase"]))
                # ba = cl.get_balance_allowance()

                # from py_clob_client_v2.clob_types import AssetType
                # try:
                #     ba = cl.get_balance_allowance(asset_type=AssetType.COLLATERAL)
                # except Exception:
                #     ba = cl.get_balance_allowance(asset_type="COLLATERAL")

                # cash = float(ba.get("balance", 0)) / 1e6

                ba, _cerr = None, None
                for _call in (
                    lambda: cl.get_balance_allowance("COLLATERAL"),
                    lambda: cl.get_balance_allowance(),
                    lambda: cl.get_balance_allowance(asset_type="COLLATERAL"),
                ):
                    try:
                        ba = _call()
                        break
                    except TypeError as _te:
                        _cerr = str(_te)[:80]; continue
                    except Exception as _e:
                        _cerr = str(_e)[:100]; break
                if ba is not None:
                    cash = float(ba.get("balance", 0)) / 1e6
                elif _cerr:
                    res["cash_err"] = _cerr

        except Exception as e:
            res["cash_err"] = str(e)[:100]
        pv = 0.0
        for addr in (funder, res["signer"]):
            try:
                rp = httpx.get("https://data-api.polymarket.com/positions",
                               params={"user": addr, "limit": 100}, timeout=15)
                # for p in rp.json():
                #     pv += float(p.get("curValue") or 0)

                for p in rp.json():
                    v = 0.0
                    for k in ("curValue", "currentValue", "usdcValue",
                              "marketValue", "value"):
                        if float(p.get(k) or 0) > 0:
                            v = float(p[k]); break
                    if v == 0.0:
                        v = float(p.get("size") or 0) * \
                            float(p.get("curPrice") or p.get("price") or 0)
                    pv += v
                    
                if pv > 0:
                    break
            except Exception as e:
                res["pos_err"] = str(e)[:100]
        res["cash_usd"] = round(cash, 2) if cash is not None else None
        res["posisi_usd"] = round(pv, 2)
        res["web_usd"] = round((cash or 0) + pv, 2)
        res["catatan"] = "cash ledger CLOB + nilai posisi data-api"
        res["status"] = "ok"

    except Exception as e:
        res["geoblock"] = ("403" in str(e)) or ("region" in str(e).lower())        
        res["error"] = str(e)
    return res


def get_all_saldo():
    creds = load_creds()
    return {
        "kalshi": get_saldo_kalshi(creds.get("kalshi", {})),
        "limitless": get_saldo_limitless(creds.get("limitless", {})),
        "polymarket": get_saldo_polymarket(creds.get("polymarket", {})),
    }