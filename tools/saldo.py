# tools/saldo.py
"""
Cek saldo terpadu semua venue (Kalshi, Limitless, Polymarket).
Jalankan: uv run tools/saldo.py
"""
import base64
import json
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


def saldo_kalshi(c):
    res = {"venue": "kalshi"}
    r = kalshi_get(c, '/trade-api/v2/portfolio/balance')
    if r.status_code == 200:
        d = r.json()
        res["cash_usd"] = float(d.get("balance_dollars", 0))
        res["portfolio_cents"] = int(d.get("portfolio_value", 0))
    r2 = kalshi_get(c, '/trade-api/v2/portfolio/positions')
    if r2.status_code == 200:
        pos = r2.json()
        res["posisi_market"] = [{
            "ticker": m.get("market_ticker") or m.get("ticker") or "?",
            "cost_usd": m.get("total_cost_dollars"),
            "fees_usd": m.get("fees_paid_dollars"),
        } for m in pos.get("market_positions", [])[:10]]
        res["posisi_event"] = [{
            "event": e.get("event_ticker"),
            "exposure_usd": e.get("event_exposure_dollars"),
        } for e in pos.get("event_positions", [])[:5]]
    return res


def saldo_limitless(c):
    res = {"venue": "limitless"}
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
    return res


def saldo_polymarket(c):
    from eth_account import Account
    res = {"venue": "polymarket"}
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
    res["catatan"] = "saldo web ($19.95) di ledger internal Polymarket"
    return res


def main():
    creds = load_creds()
    print("=" * 72)
    print("💰 SALDO SEMUA VENUE")
    print("=" * 72)

    k = saldo_kalshi(creds.get("kalshi", {}))
    print("\n[1] KALSHI")
    print(f"  cash         : ${k.get('cash_usd', 0):.4f}")
    print(f"  portfolio    : ${k.get('portfolio_cents', 0) / 100:.2f} (nilai posisi aktif)")
    for p in k.get("posisi_market", []):
        print(f"  posisi market: {p['ticker']} cost=${p['cost_usd']} fees=${p['fees_usd']}")
    for e in k.get("posisi_event", []):
        print(f"  posisi event : {e['event']} exposure=${e['exposure_usd']}")

    l = saldo_limitless(creds.get("limitless", {}))
    print("\n[2] LIMITLESS")
    print(f"  smart wallet : {l.get('smart_wallet')}")
    print(f"  USDC (Base)  : {l.get('usdc_base', 0):.4f}")

    p = saldo_polymarket(creds.get("polymarket", {}))
    print("\n[3] POLYMARKET")
    print(f"  signer       : {p.get('signer')}")
    print(f"  proxy        : {p.get('proxy')}")
    print(f"  USDC.e signer: {p.get('usdce_signer', 0):.4f}")
    print(f"  USDC.e proxy : {p.get('usdce_proxy', 0):.4f}")
    print(f"  catatan      : {p.get('catatan')}")
    print("=" * 72)


if __name__ == "__main__":
    main()