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
            res["posisi_market"] = len(pos.get("market_positions", []))
            res["posisi_event"] = len(pos.get("event_positions", []))
    except Exception as e:
        res["error"] = str(e)
    return res


def get_saldo_limitless(c):
    res = {"venue": "limitless", "status": "unknown"}
    try:
        me = httpx.get("https://api.limitless.exchange/profiles/me",
                       headers=_lim_hmac(c, "GET", "/profiles/me"),
                       timeout=10).json()
        sw = me.get("smartWallet")
        res["smart_wallet"] = sw
        
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


def get_saldo_polymarket(c):
    from eth_account import Account
    res = {"venue": "polymarket", "status": "unknown"}
    try:
        res["signer"] = Account.from_key(c.get("private_key", "")).address
        res["proxy"] = c.get("proxy_address", "")
        
        def bal(tok, a):
            data = "0x70a08231" + a[2:].lower().rjust(64, "0")
            r = httpx.post("https://polygon-rpc.com",
                           json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                 "params": [{"to": tok, "data": data}, "latest"]},
                           timeout=10)
            return int(r.json().get("result") or "0x0", 16) / 1e6

        USDCe = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        res["usdce_signer"] = bal(USDCe, res["signer"])
        res["usdce_proxy"] = bal(USDCe, res["proxy"])
        res["web_usd"] = 19.95  # hardcode dari web (off-chain)
        res["catatan"] = "saldo web di ledger internal (off-chain)"
        res["status"] = "ok"
    except Exception as e:
        res["error"] = str(e)
    return res


def get_all_saldo():
    creds = load_creds()
    return {
        "kalshi": get_saldo_kalshi(creds.get("kalshi", {})),
        "limitless": get_saldo_limitless(creds.get("limitless", {})),
        "polymarket": get_saldo_polymarket(creds.get("polymarket", {})),
    }