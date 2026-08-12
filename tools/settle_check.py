"""
Settlement Check — Tahap 9.
Poll resolusi trade paper → rekonsiliasi → ledger → CSV → alert konflik.
"""
import sys
import asyncio
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from rich.console import Console
from rich.table import Table

from app.settlement import (fetch_poly_resolution, fetch_kalshi_resolution,
                            compute_settlement, export_csv, LEDGER_FILE)
from app.execution.paper_executor import PAPER_LEDGER
from app.alerts.telegram import send_text

console = Console()


async def main():
    trades = json.loads(PAPER_LEDGER.read_text()) if PAPER_LEDGER.exists() else []
    if not trades:
        console.print("[yellow]Belum ada trade paper untuk di-settle.[/yellow]")
        return

    ledger = json.loads(LEDGER_FILE.read_text()) if LEDGER_FILE.exists() else []
    done = {(r.get("key"), r.get("ts")) for r in ledger}

    new_rows = []
    async with httpx.AsyncClient() as client:
        for rec in trades:
            if (rec.get("key"), rec.get("ts")) in done:
                continue
            resolutions = {}
            for o in rec.get("orders", []):
                if o["venue"] == "polymarket":
                    resolutions[(o["venue"], o["market_id"])] = \
                        await fetch_poly_resolution(client, o["market_id"])
                elif o["venue"] == "kalshi":
                    resolutions[(o["venue"], o["market_id"])] = \
                        await fetch_kalshi_resolution(client, o["market_id"])
            s = compute_settlement(rec, resolutions)
            new_rows.append(s)
            if s["status"] != "PENDING":
                ledger.append(s)
            if s["status"] == "SETTLEMENT_CONFLICT":
                await send_text(
                    f"🚨 <b>SETTLEMENT CONFLICT</b>\n{rec.get('key')}\n"
                    f"Hasil bukan 1-1 → indikasi false-friend. Periksa manual!"
                )

    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_FILE.write_text(json.dumps(ledger, indent=2, default=str))
    csv_path = export_csv(ledger, Path("data/reports/laporan_klien.csv"))

    table = Table(title="Rekonsiliasi Settlement")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Realized", justify="right")
    table.add_column("Expected", justify="right")
    for s in new_rows:
        table.add_row(str(s["key"]), s["status"],
                      str(s["realized_pnl"]), str(s["expected_pi"]))
    console.print(table)
    console.print(f"[dim]📄 Laporan CSV: {csv_path}[/dim]")


if __name__ == "__main__":
    asyncio.run(main())