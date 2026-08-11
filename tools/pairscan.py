"""
Pair Scanner — mengambil data dari Polymarket & Kalshi,
mencocokkan market yang sama, menampilkan LOCK/SKIP di terminal.

Penggunaan: uv run tools/pairscan.py
"""
# === TAMBAHKAN PATH PROYEK KE PYTHON ===
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
# ========================================

import asyncio
import json
import os
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from app.mapper.normalizer import normalize_polymarket, normalize_kalshi
from app.mapper.matcher import pair_markets, SkipCode

# ==========================
# KONFIGURASI
# ==========================
LIMIT_PER_VENUE = 50
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "application/json",
}
POLY_URL = "https://gamma-api.polymarket.com/markets"
KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
DATA_DIR = Path("data")

console = Console()


# ==========================
# FETCH DATA DARI BURSA
# ==========================
async def fetch_polymarket(client: httpx.AsyncClient) -> list:
    """Ambil 50 market aktif Polymarket sorted by 24h volume."""
    try:
        resp = await client.get(
            POLY_URL,
            params={
                "closed": "false",
                "limit": LIMIT_PER_VENUE,
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            console.print(f"[red]⚠ Polymarket HTTP {resp.status_code}[/red]")
            return []
        return resp.json()
    except Exception as e:
        console.print(f"[red]⚠ Polymarket error: {e}[/red]")
        return []


async def fetch_kalshi(client: httpx.AsyncClient) -> list:
    """Ambil 50 market aktif Kalshi."""
    try:
        resp = await client.get(
            KALSHI_URL,
            params={"limit": LIMIT_PER_VENUE, "status": "open"},
            timeout=30.0,
        )
        if resp.status_code != 200:
            console.print(f"[red]⚠ Kalshi HTTP {resp.status_code}[/red]")
            return []
        data = resp.json()
        return data.get("markets", [])
    except Exception as e:
        console.print(f"[red]⚠ Kalshi error: {e}[/red]")
        return []


# ==========================
# NORMALIZE (RAW → MARKETINFO)
# ==========================
def normalize_all(raw_poly: list, raw_kalshi: list):
    """Ubah data mentah menjadi MarketInfo dengan aman (skip yang error)."""
    poly_infos = []
    kalshi_infos = []
    poly_errors = 0
    kalshi_errors = 0

    for raw in raw_poly:
        try:
            poly_infos.append(normalize_polymarket(raw))
        except Exception:
            poly_errors += 1

    for raw in raw_kalshi:
        try:
            kalshi_infos.append(normalize_kalshi(raw))
        except Exception:
            kalshi_errors += 1

    return poly_infos, kalshi_infos, poly_errors, kalshi_errors


# ==========================
# OUTPUT DISPLAY
# ==========================
def display_results(result, raw_poly, raw_kalshi, poly_errors, kalshi_errors):
    """Tampilkan hasil LOCK/SKIP di terminal dengan Rich."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Header
    console.print()
    console.print(Panel.fit(
        f"[bold cyan]PAIR SCANNER[/bold cyan] — {now_str}\n"
        f"Scanned: [yellow]{len(raw_poly)}[/yellow] Polymarket + "
        f"[yellow]{len(raw_kalshi)}[/yellow] Kalshi",
        box=box.DOUBLE_EDGE,
    ))

    # Summary stats
    console.print(f"\n[bold]Ringkasan:[/bold]")
    console.print(f"  🔒 LOCKED     : [green]{result.lock_count}[/green] market (boleh di-arbitrase)")
    console.print(f"  ⛔ SKIPPED     : [red]{result.skip_count}[/red] market (dibuang)")
    console.print(f"  ⚠  Parse error : [yellow]{poly_errors + kalshi_errors}[/yellow]")

    # === LOCKED MARKETS ===
    if result.lock_count > 0:
        console.print(f"\n[bold green]🔒 LOCKED MARKETS ({result.lock_count}):[/bold green]")

        # Sort by close_ts (yang paling dekat settlement dulu)
        sorted_locked = sorted(result.locked, key=lambda r: r.key.close_ts)

        lock_table = Table(box=box.ROUNDED, show_lines=True)
        lock_table.add_column("#", style="bold cyan", width=3)
        lock_table.add_column("Canonical Key", style="bold white")
        lock_table.add_column("Venues", style="yellow")
        lock_table.add_column("TTL (jam)", justify="right")

        now_ts = int(datetime.now().timestamp())

        for i, lock in enumerate(sorted_locked, 1):
            venues = ", ".join(sorted({m.venue for m in lock.markets}))
            ttl_hours = (lock.key.close_ts - now_ts) / 3600
            key_str = (f"{lock.key.asset}.{lock.key.template}."
                       f"{lock.key.interval}"
                       + (f".{lock.key.strike}" if lock.key.strike else ""))

            lock_table.add_row(
                str(i),
                key_str,
                venues,
                f"{ttl_hours:.1f}" if ttl_hours > 0 else "lewat",
            )

        console.print(lock_table)

        # Detail tiap locked pair (max 5)
        for lock in sorted_locked[:5]:
            console.print(f"\n[cyan]  Detail: {lock.key.asset}.{lock.key.template}.{lock.key.interval}[/cyan]")
            for m in lock.markets:
                console.print(f"    • [{m.venue.upper()}] {m.title[:60]}")
                console.print(f"      ID: {m.venue_id} | Settlement: {m.settlement_source}")

    # === SKIPPED MARKETS (breakdown by skip code) ===
    if result.skip_count > 0:
        console.print(f"\n[bold red]⛔ SKIPPED MARKETS (breakdown):[/bold red]")

        # Hitung per skip code
        skip_breakdown = {}
        for skip_rec in result.skipped:
            code = skip_rec.skip_code.value
            if code not in skip_breakdown:
                skip_breakdown[code] = {
                    "count": 0,
                    "desc": skip_rec.skip_code.description,
                    "examples": [],
                }
            skip_breakdown[code]["count"] += 1
            if len(skip_breakdown[code]["examples"]) < 2:
                skip_breakdown[code]["examples"].append(skip_rec.market.title[:50])

        skip_table = Table(box=box.SIMPLE)
        skip_table.add_column("Kode", style="bold red", width=5)
        skip_table.add_column("Alasan", width=35)
        skip_table.add_column("Jumlah", justify="right", width=8)
        skip_table.add_column("Contoh")

        for code, info in sorted(skip_breakdown.items()):
            example = info["examples"][0] if info["examples"] else "-"
            skip_table.add_row(
                code,
                info["desc"],
                str(info["count"]),
                example[:45],
            )

        console.print(skip_table)


# ==========================
# SAVE RAW DATA
# ==========================
def save_scan_data(result, raw_poly, raw_kalshi):
    """Simpan hasil scan ke file JSON untuk audit."""
    DATA_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = DATA_DIR / f"scan_{ts}.json"

    payload = {
        "timestamp": ts,
        "summary": {
            "poly_count": len(raw_poly),
            "kalshi_count": len(raw_kalshi),
            "locked": result.lock_count,
            "skipped": result.skip_count,
        },
        "locked": [
            {
                "key": lock.key.to_dict(),
                "markets": [
                    {"venue": m.venue, "title": m.title, "venue_id": m.venue_id}
                    for m in lock.markets
                ],
            }
            for lock in result.locked
        ],
        "skipped_breakdown": {},
    }

    # Breakdown skip
    for skip_rec in result.skipped:
        code = skip_rec.skip_code.value
        if code not in payload["skipped_breakdown"]:
            payload["skipped_breakdown"][code] = {
                "desc": skip_rec.skip_code.description,
                "count": 0,
            }
        payload["skipped_breakdown"][code]["count"] += 1

    with open(filepath, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    console.print(f"\n[dim]📁 Hasil disimpan ke: {filepath}[/dim]")


# ==========================
# MAIN
# ==========================
async def main():
    console.print("\n[bold cyan]🔍 Starting Pair Scan...[/bold cyan]")
    console.print(f"[dim]Mengambil {LIMIT_PER_VENUE} market dari tiap venue...[/dim]")

    async with httpx.AsyncClient(headers=HEADERS) as client:
        raw_poly, raw_kalshi = await asyncio.gather(
            fetch_polymarket(client),
            fetch_kalshi(client),
        )

    console.print(f"[dim]Normalizing data...[/dim]")
    poly_infos, kalshi_infos, poly_errors, kalshi_errors = normalize_all(raw_poly, raw_kalshi)

    console.print(f"[dim]Running matcher...[/dim]")
    result = pair_markets(poly_infos, kalshi_infos, [])

    display_results(result, raw_poly, raw_kalshi, poly_errors, kalshi_errors)
    save_scan_data(result, raw_poly, raw_kalshi)

    console.print("\n[bold green]✅ Scan selesai.[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())