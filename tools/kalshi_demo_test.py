"""
Kalshi Demo Integration Test — Tahap 11.5 (Opsi C), versi API V2.
Pemakaian:
  uv run tools/kalshi_demo_test.py            # cek saldo demo
  uv run tools/kalshi_demo_test.py --order    # create order V2 + cancel V2
"""
import sys
import os
import time
import json
import base64
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv()

BASE = os.getenv("KALSHI_DEMO_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")
KEY_ID = os.getenv("KALSHI_DEMO_KEY_ID", "")
PEM_PATH = Path(os.path.expanduser(
    os.getenv("KALSHI_DEMO_PRIVATE_KEY_PATH", "~/kalshi_demo.pem")))


def headers(method: str, path: str) -> dict:
    """RSA-PSS sesuai docs: sign '/trade-api/v2' + path, tanpa query params."""
    ts = str(int(time.time() * 1000))
    sign_path = "/trade-api/v2" + path
    msg = f"{ts}{method}{sign_path}".encode()
    key = serialization.load_pem_private_key(PEM_PATH.read_bytes(), password=None)
    sig = key.sign(
        msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }


def show(title: str, resp: httpx.Response) -> httpx.Response:
    print(f"\n=== {title} ===")
    print("Status:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2)[:1200])
    except Exception:
        print(resp.text[:400])
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", action="store_true",
                    help="Create 1 order limit demo (V2) lalu cancel")
    args = ap.parse_args()

    if not KEY_ID or not PEM_PATH.exists():
        sys.exit("⚠ Isi .env: KALSHI_DEMO_KEY_ID & KALSHI_DEMO_PRIVATE_KEY_PATH")

    # 1) Saldo demo — bukti autentikasi RSA-PSS bekerja
    show("SALDO DEMO", httpx.get(
        BASE + "/portfolio/balance",
        headers=headers("GET", "/portfolio/balance"), timeout=15))

    if not args.order:
        return

    # # 2) Pilih market binary dengan likuiditas
    # r = httpx.get(BASE + "/markets?limit=100&status=open",
    #               headers=headers("GET", "/markets"), timeout=15)
    # markets = r.json().get("markets", []) if r.status_code == 200 else []
    # pick = None
    # for m in markets:
    #     try:
    #         liq = float(m.get("liquidity_dollars", 0) or 0)
    #     except Exception:
    #         liq = 0
    #     if m.get("market_type") == "binary" and not m.get("is_provisional") and liq > 0:
    #         pick = m
    #         break
    # if not pick and markets:
    #     pick = markets[0]
    # if not pick:
    #     sys.exit("⚠ Tidak ada market terbuka.")

    # ticker = pick["ticker"]
    # print("\nTicker dipilih:", ticker, "| liquidity:", pick.get("liquidity_dollars"))

    # 2) Pilih market: prioritas shard 0, binary, non-provisional, likuid
    r = httpx.get(BASE + "/markets?limit=200&status=open",
                  headers=headers("GET", "/markets"), timeout=15)
    markets = r.json().get("markets", []) if r.status_code == 200 else []

    def liq_of(m):
        try:
            return float(m.get("liquidity_dollars", 0) or 0)
        except Exception:
            return 0

    shard0 = [m for m in markets if m.get("exchange_index", 0) == 0]
    cands = [m for m in shard0 if m.get("market_type") == "binary"
             and not m.get("is_provisional")]
    cands.sort(key=liq_of, reverse=True)
    pick = (cands or shard0 or markets)[0]

    ticker = pick["ticker"]
    print("\nTicker dipilih:", ticker,
          "| shard:", pick.get("exchange_index"),
          "| liq:", pick.get("liquidity_dollars"))
    
    # 3) ORDER V2: limit bid 1 kontrak @ 5¢ (GTC) — lalu cancel
    payload = {
        "ticker": ticker,
        "side": "bid",                      # bid = beli YES
        "count": "1.00",
        "price": "0.0500",                  # fixed-point dollars
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": f"arb-demo-{int(time.time())}",
        "exchange_index": -1,               # auto-route by ticker
    }
    ro = show("ORDER V2", httpx.post(
        BASE + "/portfolio/events/orders",
        headers=headers("POST", "/portfolio/events/orders"),
        json=payload, timeout=15))

    if ro.status_code == 201:
        data = ro.json()
        oid = data.get("order_id")
        print("\norder_id:", oid,
              "| fill:", data.get("fill_count"),
              "| remaining:", data.get("remaining_count"))

        # 4) CANCEL V2
        rc = show("CANCEL V2", httpx.delete(
            BASE + f"/portfolio/events/orders/{oid}",
            headers=headers("DELETE", f"/portfolio/events/orders/{oid}"),
            timeout=15))
        if rc.status_code == 200:
            print("\n✅ Siklus order demo lengkap: create → cancel.")


if __name__ == "__main__":
    main()