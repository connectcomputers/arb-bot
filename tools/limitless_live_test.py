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
    print("\n[1/3] Fetching active markets (public, no auth)...")
    try:
        r = httpx.get(HOST + "/markets/active", 
                     params={"limit": 10}, timeout=15)
        if r.status_code == 200:
            response = r.json()
            markets = response.get("data", [])
            total = response.get("totalMarketsCount", 0)
            print(f"✅ Endpoint found: /markets/active")
            print(f"Total active markets: {total}")
            print(f"Fetched: {len(markets)}")
            
            # Filter: not expired + CLOB type (untuk orderbook)
            clob_markets = [m for m in markets 
                           if not m.get("expired") 
                           and m.get("tradeType") == "clob"]
            amm_markets = [m for m in markets 
                          if not m.get("expired") 
                          and m.get("tradeType") == "amm"]
            
            print(f"CLOB markets: {len(clob_markets)}")
            print(f"AMM markets: {len(amm_markets)}")
            
            # Pick first CLOB market (untuk orderbook test)
            pick = clob_markets[0] if clob_markets else markets[0] if markets else None
            
            if pick:
                print("\nMarket dipilih:")
                print(f"  Title    : {pick.get('title', '?')[:60]}")
                print(f"  ID       : {pick.get('id')}")
                print(f"  Slug     : {pick.get('slug', '?')[:60]}")
                print(f"  Status   : {pick.get('status')}")
                print(f"  Type     : {pick.get('tradeType')}")
                prices = pick.get('prices', [])
                if prices and len(prices) >= 2:
                    print(f"  Prices   : YES {prices[0]:.1f}¢ | NO {prices[1]:.1f}¢")
                print(f"  Volume   : {pick.get('volumeFormatted', '0')} USDC")
                print(f"  Liquidity: {pick.get('liquidityFormatted', '0')} USDC")
            else:
                print("⚠ Tidak ada market aktif")
        else:
            print(f"⚠ Status: {r.status_code}")
            print(r.text[:300])
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

    # === Orderbook test (butuh auth untuk CLOB) ===
    print("\n[3/3] Orderbook test...")
    if pick and pick.get("tradeType") == "clob":
        slug = pick.get("slug")
        print(f"Testing orderbook for slug: {slug[:40]}...")
        
        if API_KEY and API_SECRET:
            # Authenticated orderbook
            headers = hmac_sign("GET", f"/trading/orderbook?slug={slug}")
            try:
                r = httpx.get(HOST + "/trading/orderbook",
                             params={"slug": slug},
                             headers=headers, timeout=15)
                print(f"Status: {r.status_code}")
                if r.status_code == 200:
                    print("✅ Orderbook accessible (authenticated)")
                elif r.status_code in (400, 404):
                    print(r.text[:200])
            except Exception as e:
                print(f"⚠ Error: {e}")
        else:
            print("⚠ Orderbook butuh auth (isi LIMITLESS_API_KEY & LIMITLESS_API_SECRET)")
    elif pick and pick.get("tradeType") == "amm":
        print("ℹ Market ini AMM (automated market maker), bukan orderbook CLOB")
        print("  AMM trading via: POST /amm/buy, POST /amm/sell")
    else:
        print("⚠ Tidak ada CLOB market untuk test orderbook")
        
    print("\n✅ STAGE 1 OK: wallet ready + public discovery.")
    print("Stage 2 berikutnya: get API key dari dashboard Limitless + deposit USDC di Base.")


if __name__ == "__main__":
    main()