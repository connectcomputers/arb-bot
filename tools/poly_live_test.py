"""
Polymarket Live Test — Tahap 11.6 (T2).
Stage 1: auth L1/L2 + market discovery + orderbook (tanpa dana).
Pemakaian: uv run tools/poly_live_test.py
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
load_dotenv()

from eth_account import Account
from py_clob_client_v2 import ClobClient

HOST = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
CHAIN = 137
PK = os.getenv("POLY_TEST_PK", "")


def main():
    if not PK:
        sys.exit("⚠ Isi POLY_TEST_PK di .env dulu.")

    acct = Account.from_key(PK)
    print("Wallet uji   :", acct.address)

    # === L1 auth (EIP-712) → derive creds L2 ===
    c1 = ClobClient(host=HOST, chain_id=CHAIN, key=PK)
    creds = c1.create_or_derive_api_key()
    try:
        key_str = getattr(creds, "api_key", None) or creds.get("api_key")
    except Exception:
        key_str = str(creds)
    print("API key CLOB :", str(key_str)[:8] + "… (derived OK)")

    # === Market discovery: binary aktif paling likuid ===
    r = httpx.get(GAMMA + "/markets", params={
        "closed": "false", "limit": 20,
        "order": "volume24hr", "ascending": "false",
    }, timeout=15)
    markets = r.json() if r.status_code == 200 else []
    pick = None
    for m in markets:
        try:
            toks = json.loads(m.get("clobTokenIds", "[]"))
            if toks and m.get("active"):
                pick = (m, toks)
                break
        except Exception:
            continue
    if not pick:
        sys.exit("⚠ Tidak ada market aktif.")
    m, toks = pick
    print("Market       :", (m.get("question") or "?")[:60])
    print("token_id YES :", toks[0][:24] + "…")

    # === Orderbook publik ===
    b = httpx.get(HOST + "/book", params={"token_id": toks[0]}, timeout=15)
    if b.status_code == 200:
        book = b.json()
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        bb = max((float(x["price"]) for x in bids), default=None)
        ba = min((float(x["price"]) for x in asks), default=None)
        print("Best bid     :", bb)
        print("Best ask     :", ba)

    print("\n✅ STAGE 1 OK: auth L1/L2 + discovery + orderbook.")
    print("Stage 2 berikutnya: fund wallet ±$10 → order mikro.")


if __name__ == "__main__":
    main()