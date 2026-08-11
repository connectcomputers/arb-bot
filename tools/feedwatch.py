import asyncio
import httpx

# Identitas browser asli untuk menembus firewall dasar
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "application/json"
}

async def fetch_polymarket():
    """Ambil 3 market terlaris dari Polymarket."""
    async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
        response = await client.get(
            "https://gamma-api.polymarket.com/markets",
            params={"closed": "false", "limit": 3, "order": "volume24hr", "ascending": "false"}
        )
        if response.status_code == 200:
            return response.json()
        print(f"⚠️ Polymarket Error: Status {response.status_code}")
        return []

async def fetch_kalshi():
    """Ambil 3 market terbaru dari Kalshi."""
    async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
        response = await client.get(
            "https://external-api.kalshi.com/trade-api/v2/markets",
            params={"limit": 3, "status": "open"}
        )
        
        # PERISAI: Cek apakah Kalshi membalas dengan sukses (200)
        if response.status_code != 200:
            print(f"⚠️ Kalshi memblokir atau error (Status {response.status_code}).")
            # Cetak 100 huruf pertama dari balasan server untuk diagnosa
            print(f"Isi balasan server: {response.text[:100]}...")
            return {"markets": []} # Kembalikan list kosong agar tidak crash
            
        return response.json()

async def main():
    print("=" * 60)
    print("POLYMARKET — Top 3 Markets by 24h Volume")
    print("=" * 60)
    poly_data = await fetch_polymarket()
    for i, market in enumerate(poly_data, 1):
        title = market.get("question", "N/A")[:50]
        volume = market.get("volume24hr", 0)
        print(f"{i}. {title}")
        print(f"   Volume 24h: ${volume:,.0f}\n")
    
    print("=" * 60)
    print("KALSHI — 3 Newest Markets")
    print("=" * 60)
    kalshi_data = await fetch_kalshi()
    
    # Jika kalshi_data isinya kosong (karena diblokir), loop ini otomatis dilewati
    for i, market in enumerate(kalshi_data.get("markets", []), 1):
        title = market.get("title", "N/A")[:50]
        yes_price = market.get("yes_price", "?")
        print(f"{i}. {title}")
        print(f"   YES price: {yes_price}\n")
    
    print("=" * 60)
    print("✅ Script selesai dijalankan!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())