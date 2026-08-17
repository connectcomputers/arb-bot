"""
Polymarket LIVE Order Tool — uji penerimaan eksekusi real (manual trigger).
Pemakaian:
  uv run tools/poly_live_order.py status
  uv run tools/poly_live_order.py book
  uv run tools/poly_live_order.py place [--price 0.05] [--size 1]
  uv run tools/poly_live_order.py buy [--size 1]
  uv run tools/poly_live_order.py cancel --id ORDER_ID
  uv run tools/poly_live_order.py cancel-all
"""
import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
load_dotenv()

from eth_account import Account
from py_clob_client_v2 import (ClobClient, OrderArgs, OrderType, Side,
                               PartialCreateOrderOptions, MarketOrderArgs)

HOST = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
CHAIN = 137
PK = os.getenv("POLY_LIVE_PK", "")


def get_client():
    c1 = ClobClient(host=HOST, chain_id=CHAIN, key=PK)
    creds = c1.create_or_derive_api_key()
    return ClobClient(host=HOST, chain_id=CHAIN, key=PK, creds=creds)


def pick_market():
    r = httpx.get(GAMMA + "/markets", params={
        "closed": "false", "limit": 30,
        "order": "volume24hr", "ascending": "false"}, timeout=15)
    for m in r.json():
        try:
            toks = json.loads(m.get("clobTokenIds", "[]"))
            tick = m.get("tickSize") or "0.01"
            if toks and m.get("active"):
                b = httpx.get(HOST + "/book", params={"token_id": toks[0]}, timeout=15).json()
                bids, asks = b.get("bids", []), b.get("asks", [])
                if bids and asks:
                    bb = max(float(x["price"]) for x in bids)
                    ba = min(float(x["price"]) for x in asks)
                    if 0.05 < ba < 0.95:
                        return m, toks[0], tick, bb, ba
        except Exception:
            continue
    return None, None, None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "book", "place", "buy", "cancel", "cancel-all"])
    ap.add_argument("--price", type=float, default=None)
    ap.add_argument("--size", type=float, default=1)
    ap.add_argument("--id", default=None)
    args = ap.parse_args()

    if not PK:
        sys.exit("⚠ Isi POLY_LIVE_PK di .env")

    if args.cmd == "status":
        acct = Account.from_key(PK)
        print("Wallet :", acct.address)
        client = get_client()
        print("✅ Auth L1/L2 OK (API key derived)")
        print("ℹ Saldo/posisi: cek bersamaan di polymarket.com (wallet sama)")
        return

    client = get_client()

    if args.cmd == "cancel-all":
        for fn in ("cancel_all", "cancelAll"):
            try:
                print(getattr(client, fn)()); return
            except Exception:
                continue
        sys.exit("⚠ cancel_all tidak tersedia di SDK ini")

    if args.cmd == "cancel":
        for fn in ("cancel", "cancel_order"):
            try:
                print(getattr(client, fn)(args.id)); return
            except Exception:
                continue
        sys.exit("⚠ cancel gagal")

    m, tid, tick, bb, ba = pick_market()
    if not tid:
        sys.exit("⚠ Tidak ada market likuid")
    print("Market :", (m.get("question") or "?")[:60])
    print(f"Best bid {bb} | best ask {ba} | tick {tick}")

    if args.cmd == "book":
        return

    if args.cmd == "place":
        price = args.price or round(bb, 2)
        resp = client.create_and_post_order(
            OrderArgs(token_id=tid, price=price, size=args.size, side=Side.BUY),
            options=PartialCreateOrderOptions(tick_size=tick),
            order_type=OrderType.GTC)
        print("ORDER RESTING →", json.dumps(resp, default=str)[:400])
        return

    if args.cmd == "buy":
        # Marketable: limit BUY di best ask (FAK) → fill instan
        try:
            resp = client.create_and_post_order(
                OrderArgs(token_id=tid, price=ba, size=args.size, side=Side.BUY),
                options=PartialCreateOrderOptions(tick_size=tick),
                order_type=OrderType.FAK)
        except Exception as e:
            print("FAK gagal, fallback market order:", e)
            resp = client.create_and_post_market_order(
                MarketOrderArgs(token_id=tid, amount=1.0, side=Side.BUY,
                                order_type=OrderType.FAK),
                options=PartialCreateOrderOptions(tick_size=tick),
                order_type=OrderType.FAK)
        print("ORDER FILL →", json.dumps(resp, default=str)[:400])


if __name__ == "__main__":
    main()