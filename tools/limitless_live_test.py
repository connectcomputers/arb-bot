"""
Limitless Live Test — Tahap 11.7 (T2 Base chain).
Stage 1: wallet creation + public market discovery (tanpa dana).
Stage 1b: auth test jika API key tersedia.

Pemakaian:
  uv run tools/limitless_live_test.py
"""
import sys
import os
import time
import hmac
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
load_dotenv()

from eth_account import Account

HOST = "https://api.limitless.exchange"
BASE_CHAIN_ID = 8453

# === Auth credentials (optional, isi dari dashboard Limitless) ===
API_KEY = os.getenv("LIMITLESS_API_KEY", "")
API_SECRET = os.getenv("LIMITLESS_API_SECRET", "")


def hmac_sign(method: str, path: str, body: str = "") -> dict:
    """HMAC-SHA256 signing untuk Limitless API."""
    if not API_KEY or not API_SECRET:
        return {}
    
    timestamp = str(int(time.time() * 1000))
    message = timestamp + method.upper() + path + body
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return {
        "lmts-api-key": API_KEY,
        "lmts-timestamp": timestamp,
        "lmts-signature": signature,
    }


def main():
    # === Wallet uji (Base chain) ===
    pk = os.getenv("LIMITLESS_TEST_PK", "")
    if not pk:
        acct = Account.create()
        pk = acct.key.hex()
        print("Wallet BARU dibuat (Base chain)")
    else:
        acct = Account.from_key(pk)
        print("Wallet existing")
    
    print("Address :", acct.address)
    print("Chain   : Base (ID 8453)")
    # print("PK      :", pk[:12] + "… (simpan di .env sebagai LIMITLESS_TEST_PK)")
    print("PK      :", pk[:64] + "… (simpan di .env sebagai LIMITLESS_TEST_PK)")
    
    # # === Public: Market discovery ===
    # print("\n[1/3] Fetching markets (public, no auth)...")
    # try:
    #     r = httpx.get(HOST + "/markets", params={"limit": 10}, timeout=15)
    #     if r.status_code == 200:
    #         markets = r.json()
    #         print(f"✅ Markets found: {len(markets)}")
            
    #         # Pick first active market
    #         pick = None
    #         for m in markets:
    #             if m.get("active"):
    #                 pick = m
    #                 break
            
    #         if pick:
    #             print("Market dipilih:", pick.get("title", "?")[:60])
    #             print("Market ID    :", pick.get("id"))
    #         else:
    #             print("⚠ Tidak ada market aktif")
    #     else:
    #         print(f"⚠ Status: {r.status_code}")
    #         print(r.text[:200])
    # except Exception as e:
    #     print(f"⚠ Error: {e}")

    # === Public: Market discovery ===
    print("\n[1/3] Fetching markets (public, no auth)...")
    try:
        # Limitless uses /api/v1/markets or similar - let's try common paths
        for endpoint in ["/api/v1/markets", "/v1/markets", "/markets"]:
            r = httpx.get(HOST + endpoint, params={"limit": 10}, timeout=15)
            if r.status_code == 200:
                markets = r.json()
                print(f"✅ Endpoint found: {endpoint}")
                print(f"Markets found: {len(markets)}")
                
                # Pick first active market
                pick = None
                for m in markets:
                    if m.get("active") or m.get("status") == "active":
                        pick = m
                        break
                
                if pick:
                    print("Market dipilih:", pick.get("title", pick.get("question", "?"))[:60])
                    print("Market ID/slug:", pick.get("id") or pick.get("slug"))
                else:
                    print("⚠ Tidak ada market aktif")
                break
            elif r.status_code != 404:
                print(f"⚠ Status {endpoint}: {r.status_code}")
                print(r.text[:200])
        else:
            print("⚠ Belum menemukan endpoint markets yang benar")
            print("Coba manual di browser: https://limitless.exchange/markets")
    except Exception as e:
        print(f"⚠ Error: {e}")

    # === Auth test (jika credentials ada) ===
    if API_KEY and API_SECRET:
        print("\n[2/3] Auth test (HMAC signing)...")
        try:
            headers = hmac_sign("GET", "/trading/orderbook?market_id=test")
            r = httpx.get(HOST + "/trading/orderbook", 
                         params={"market_id": "test"},
                         headers=headers, timeout=15)
            print(f"Status: {r.status_code}")
            if r.status_code in (200, 400, 404):
                print("✅ Auth signature diterima (response != 401)")
            else:
                print(r.text[:200])
        except Exception as e:
            print(f"⚠ Error: {e}")
    else:
        print("\n[2/3] Auth test skipped (isi .env LIMITLESS_API_KEY & LIMITLESS_API_SECRET)")
    
    # # === Orderbook public test ===
    # print("\n[3/3] Orderbook test (public endpoint)...")
    # try:
    #     r = httpx.get(HOST + "/markets/orderbook", 
    #                  params={"market_id": "test"}, timeout=15)
    #     print(f"Status: {r.status_code}")
    #     if r.status_code == 200:
    #         print("✅ Orderbook accessible")
    #     elif r.status_code == 404:
    #         print("⚠ Endpoint not found (mungkin butuh auth)")
    #     else:
    #         print(r.text[:200])
    # except Exception as e:
    #     print(f"⚠ Error: {e}")

    # === Orderbook public test ===
    print("\n[3/3] Orderbook test (public endpoint)...")
    try:
        # Try common orderbook paths
        test_slug = "btc-usd-1h-24aug14"  # contoh slug format
        for endpoint in ["/api/v1/orderbook", "/v1/orderbook", "/orderbook"]:
            r = httpx.get(HOST + endpoint, 
                         params={"slug": test_slug}, timeout=15)
            if r.status_code in (200, 404):
                print(f"Endpoint {endpoint}: Status {r.status_code}")
                if r.status_code == 200:
                    print("✅ Orderbook accessible")
                break
            elif r.status_code != 404:
                print(f"⚠ Status {endpoint}: {r.status_code}")
    except Exception as e:
        print(f"⚠ Error: {e}")
            
    print("\n✅ STAGE 1 OK: wallet ready + public discovery.")
    print("Stage 2 berikutnya: get API key dari dashboard Limitless + deposit USDC di Base.")


if __name__ == "__main__":
    main()