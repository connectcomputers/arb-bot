"""
Live Opportunity Pipeline — Minggu 6.
Menyatukan: Scanner → Mapper → Orderbook → Signal Engine → Terminal display.
"""
# === PATH SETUP ===
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from datetime import datetime

import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from app.mapper.normalizer import normalize_polymarket, normalize_kalshi
from app.mapper.matcher import pair_markets
from app.signal.engine import evaluate_pair
from app.orderbook import fetch_kalshi_orderbook, fetch_polymarket_orderbook
from app.execution.paper_executor import build_paper_orders, save_paper_trade

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "application/json",
}
POLY_URL = "https://gamma-api.polymarket.com/markets"
KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
# LIMIT_PER_VENUE = 50
LIMIT_PER_VENUE = 200

console = Console()


async def fetch_markets(client: httpx.AsyncClient):
    """Fetch market lists dari kedua venue."""
    poly_resp, kalshi_resp = await asyncio.gather(
        client.get(POLY_URL, params={"closed": "false", "limit": LIMIT_PER_VENUE,
                                     "order": "volume24hr", "ascending": "false"},
                   timeout=30.0),
        client.get(KALSHI_URL, params={"limit": LIMIT_PER_VENUE, "status": "open"},
                   timeout=30.0),
    )
    
    raw_poly = poly_resp.json() if poly_resp.status_code == 200 else []
    kalshi_data = kalshi_resp.json() if kalshi_resp.status_code == 200 else {}
    raw_kalshi = kalshi_data.get("markets", [])
    
    return raw_poly, raw_kalshi


async def enrich_with_orderbook(client, lock_record):
    """Untuk satu LOCKED pair, ambil orderbook dari tiap venue."""
    markets = lock_record.markets
    
    for market in markets:
        if market.venue == "kalshi":
            ob = await fetch_kalshi_orderbook(client, market.venue_id)
            market.yes_price = ob.yes_best_ask
            market.no_price = ob.no_best_ask
        elif market.venue == "polymarket":
            ob = await fetch_polymarket_orderbook(client, market.venue_id)
            market.yes_price = ob.yes_best_ask
            market.no_price = ob.no_best_ask


async def main():
    console.print("\n[bold cyan]🚀 LIVE OPPORTUNITY PIPELINE[/bold cyan]")
    console.print("[dim]Step 1/4: Scanning markets...[/dim]")
    
    async with httpx.AsyncClient(headers=HEADERS) as client:
        raw_poly, raw_kalshi = await fetch_markets(client)
    
    console.print(f"  [dim]Fetched: {len(raw_poly)} Poly + {len(raw_kalshi)} Kalshi[/dim]")
    
    console.print("[dim]Step 2/4: Matching (mapper)...[/dim]")
    poly_infos = [normalize_polymarket(m) for m in raw_poly]
    kalshi_infos = [normalize_kalshi(m) for m in raw_kalshi]
    pairing = pair_markets(poly_infos, kalshi_infos, [])
    
    console.print(f"  [dim]Locked: [green]{pairing.lock_count}[/green] | "
                  f"Skipped: [red]{pairing.skip_count}[/red][/dim]")

    # Breakdown alasan skip (transparansi)
    if pairing.skip_count > 0:
        skip_breakdown = {}
        for s in pairing.skipped:
            code = s.skip_code.value
            skip_breakdown[code] = skip_breakdown.get(code, 0) + 1
        breakdown_str = " | ".join(f"{k}:{v}" for k, v in sorted(skip_breakdown.items()))
        console.print(f"  [dim]Alasan skip → {breakdown_str}[/dim]")
    
    if pairing.lock_count == 0:
        console.print("\n[yellow]⚠ Tidak ada pair LOCKED saat ini.[/yellow]")
        
        # === DEBUG: Tampilkan contoh S10 ===
        s10_examples = [s for s in pairing.skipped if s.skip_code.value == "S10"][:10]
        if s10_examples:
            console.print("\n[bold cyan]🔍 Contoh market S10 (belum dikenali):[/bold cyan]")
            for i, skip_rec in enumerate(s10_examples, 1):
                console.print(f"  {i}. [{skip_rec.market.venue}] {skip_rec.market.title[:70]}")
                console.print(f"     Category: {skip_rec.market.category}")
        
        console.print("[dim]Tips: jalankan lagi nanti, atau tambah normalizer di Minggu 4.[/dim]")
        return
    
    console.print("[dim]Step 3/4: Fetching orderbooks (real prices)...[/dim]")
    async with httpx.AsyncClient(headers=HEADERS) as client:
        for lock in pairing.locked:
            await enrich_with_orderbook(client, lock)
    
    console.print("[dim]Step 4/4: Evaluating signal (Π-gate)...[/dim]\n")
    
    # === DISPLAY RESULTS ===
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(Panel.fit(
        f"[bold cyan]LIVE OPPORTUNITIES[/bold cyan] — {now_str}\n"
        f"Total LOCKED: [green]{pairing.lock_count}[/green]",
        box=box.DOUBLE_EDGE,
    ))
    
    table = Table(box=box.ROUNDED, show_lines=True, title="🎯 Keputusan Real-time")
    table.add_column("#", style="bold cyan", width=3)
    table.add_column("Key", style="bold white", width=30)
    table.add_column("Venues", style="yellow", width=18)
    table.add_column("P₁", justify="right", width=7)
    table.add_column("P₂", justify="right", width=7)
    table.add_column("Diskon", justify="right", width=8)
    table.add_column("Π (C=100)", justify="right", width=10)
    table.add_column("Keputusan", width=12)
    
    execute_count = 0
    wait_count = 0
    incomplete = 0
    paper_trades_recorded = 0   # ← TAMBAHKAN BARIS INI
    
    for i, lock in enumerate(pairing.locked, 1):
        markets = lock.markets
        if len(markets) < 2:
            continue
        
        m_a, m_b = markets[0], markets[1]
        
        # Jalankan signal engine
        signal = evaluate_pair(m_a, m_b, C=100)
        
        # Ambil harga yang dipakai
        p1_str = "-"
        p2_str = "-"
        if signal.direction == "YES_A_NO_B":
            if m_a.yes_price is not None:
                p1_str = f"{m_a.yes_price:.3f}"
            if m_b.no_price is not None:
                p2_str = f"{m_b.no_price:.3f}"
        elif signal.direction == "NO_A_YES_B":
            if m_a.no_price is not None:
                p1_str = f"{m_a.no_price:.3f}"
            if m_b.yes_price is not None:
                p2_str = f"{m_b.yes_price:.3f}"
        else:
            # Harga tidak lengkap
            p1_str = "?"
            p2_str = "?"
            incomplete += 1
        
        # Format key
        key_str = (f"{lock.key.asset}.{lock.key.template}."
                   f"{lock.key.interval}"
                   + (f".{lock.key.strike}" if lock.key.strike else ""))[:29]
        
        venues_str = " × ".join(sorted({m.venue.upper()[:6] for m in markets}))
        
        # Keputusan emoji
        if signal.execute:
            keputusan = "[bold green]🟢 EKSEKUSI[/bold green]"
            execute_count += 1

            # === PAPER EXECUTOR: Susun & simpan order paper ===
            paper_orders = build_paper_orders(m_a, m_b, signal)
            if paper_orders:
                key_repr = str(lock.key)
                save_paper_trade(key_repr, paper_orders, signal.pi)
                paper_trades_recorded += 1
                console.print(f"    [dim]  📝 Paper trade #{paper_trades_recorded} "
                              f"dicatat ({len(paper_orders)} order)[/dim]")
                
        elif "Harga YES/NO belum lengkap" in signal.reason:
            keputusan = "[dim]⚪ NO DATA[/dim]"
        else:
            keputusan = "[yellow]🟡 TUNGGU[/yellow]"
            wait_count += 1
        
        # Format angka
        diskon_str = f"{signal.gross_discount:.3f}"
        pi_str = f"${signal.pi:.2f}"
        
        table.add_row(
            str(i), key_str, venues_str,
            p1_str, p2_str, diskon_str, pi_str, keputusan,
        )
    
    console.print(table)
    
    # === SUMMARY ===
    console.print(f"\n[bold]📊 Ringkasan Keputusan:[/bold]")
    console.print(f"  🟢 EKSEKUSI  : [green]{execute_count}[/green]")
    console.print(f"  🟡 TUNGGU    : [yellow]{wait_count}[/yellow]")
    console.print(f"  ⚪ NO DATA   : [dim]{incomplete}[/dim]")
    console.print(f"  📝 Paper     : [cyan]{paper_trades_recorded}[/cyan] trade dicatat")  # ← BARU

    if paper_trades_recorded > 0:
        console.print(f"\n[dim]📁 Lihat detail: data/paper_trades.json[/dim]")
            
    if execute_count > 0:
        console.print(f"\n[bold green]🎉 Ada {execute_count} peluang arbitrase aktif![/bold green]")
        console.print("[dim]Catatan: untuk eksekusi real, butuh modul execution (Minggu 7).[/dim]")
    
    console.print("\n[bold green]✅ Pipeline selesai.[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())