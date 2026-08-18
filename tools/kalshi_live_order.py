"""
Kalshi LIVE Order Tool — uji eksekusi real (production, bukan demo).
Pemakaian:
  uv run tools/kalshi_live_order.py status
  uv run tools/kalshi_live_order.py book [--ticker KXBTCY-24AUG17-BTC-60000]
  uv run tools/kalshi_live_order.py place --ticker TICKER --side yes --price 50 --count 1
  uv run tools/kalshi_live_order.py buy --ticker TICKER --count 1
  uv run tools/kalshi_live_order.py cancel --id ORDER_ID
  uv run tools/kalshi_live_order.py cancel-all
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
load_dotenv()

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# BASE = os.getenv("KALSHI_BASE_URL", "https://api.kalshi.com/trade-api/v2")
BASE = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
KEY_ID = os.getenv("KALSHI_API_KEY_ID", "")
PEM_PATH = Path(os.path.expanduser(
    os.getenv("KALSHI_PRIVATE_KEY_PATH", "~/kalshi_live.pem")))


def headers(method: str, path: str) -> dict:
    """RSA-PSS signing untuk Kalshi production."""
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


def show(title: str, resp: httpx.Response):
    print(f"\n=== {title} ===")
    print("Status:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2)[:800])
    except Exception:
        print(resp.text[:400])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "book", "place", "buy", "cancel", "cancel-all"])
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--side", choices=["yes", "no"], default="yes")
    ap.add_argument("--price", type=int, default=50)  # cents
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--id", default=None)
    args = ap.parse_args()

    if not KEY_ID or not PEM_PATH.exists():
        sys.exit("⚠ Isi KALSHI_API_KEY_ID & KALSHI_PRIVATE_KEY_PATH di .env")

    if args.cmd == "status":
        r = httpx.get(BASE + "/portfolio/balance",
                     headers=headers("GET", "/portfolio/balance"), timeout=15)
        if r.status_code == 200:
            data = r.json()
            print("✅ Kalshi Auth OK")
            print(f"Saldo: ${data.get('balance_dollars', '0')}")
        else:
            print("❌ Auth failed")
            show("Error", r)
        return

    if args.cmd == "cancel-all":
        r = httpx.get(BASE + "/portfolio/orders?status=active",
                     headers=headers("GET", "/portfolio/orders"), timeout=15)
        if r.status_code == 200:
            orders = r.json().get("orders", [])
            print(f"Found {len(orders)} active orders")
            for o in orders:
                oid = o.get("order_id")
                rc = httpx.delete(
                    BASE + f"/portfolio/events/orders/{oid}",
                    headers=headers("DELETE", f"/portfolio/events/orders/{oid}"),
                    timeout=15)
                print(f"Cancel {oid}: {rc.status_code}")
        return

    if args.cmd == "cancel":
        r = httpx.delete(
            BASE + f"/portfolio/events/orders/{args.id}",
            headers=headers("DELETE", f"/portfolio/events/orders/{args.id}"),
            timeout=15)
        show("Cancel Order", r)
        return

    # Untuk book/place/buy, butuh ticker
    if not args.ticker:
        # Auto-pick market likuid
        r = httpx.get(BASE + "/markets?limit=20&status=open",
                     headers=headers("GET", "/markets"), timeout=15)
        markets = r.json().get("markets", []) if r.status_code == 200 else []
        cands = [m for m in markets if m.get("market_type") == "binary"
                and not m.get("is_provisional")
                and float(m.get("liquidity_dollars", 0) or 0) > 0]
        if not cands:
            sys.exit("⚠ Tidak ada market likuid, gunakan --ticker")
        args.ticker = cands[0]["ticker"]

    print(f"Ticker: {args.ticker}")

    if args.cmd == "book":
        r = httpx.get(BASE + f"/markets/{args.ticker}/orderbook",
                     headers=headers("GET", f"/markets/{args.ticker}/orderbook"),
                     timeout=15)
        show("Orderbook", r)
        return

    if args.cmd in ("place", "buy"):
        payload = {
            "ticker": args.ticker,
            "side": "bid" if args.side == "yes" else "ask",
            "count": str(float(args.count)),
            "price": f"{args.price/100:.4f}",
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": f"live-{int(time.time())}",
            "exchange_index": -1,
        }
        
        if args.cmd == "buy":
            # Marketable: set price tinggi (90¢) agar fill instan
            payload["price"] = "0.9000"
            payload["time_in_force"] = "immediate_or_cancel"

        r = httpx.post(BASE + "/portfolio/events/orders",
                      headers=headers("POST", "/portfolio/events/orders"),
                      json=payload, timeout=15)
        show("Order Result", r)


if __name__ == "__main__":
    main()