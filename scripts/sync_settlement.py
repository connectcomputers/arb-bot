#!/usr/bin/env python3
"""
Skrip untuk sinkronisasi settlement data dari exchange history.
Membantu mengisi data P/L yang hilang untuk posisi yang sudah close.

Cara pakai:
  cd ~/arb-bot
  python3 -m scripts.sync_settlement --dry-run    # Preview saja
  python3 -m scripts.sync_settlement --execute    # Jalankan sync
"""

import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config_store import load_creds
from app.position_manager import load_positions, save_positions
from app.venue_positions import get_positions_detailed

DATA_DIR = Path("data")
POSITIONS_FILE = DATA_DIR / "positions.json"
LIVE_STATE_FILE = DATA_DIR / "live_state.json"
BACKUP_DIR = DATA_DIR / "backups"

def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")

def backup_file(filepath):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"{filepath.name}.{int(time.time())}.bak"
    if filepath.exists():
        backup_path.write_text(filepath.read_text())
        log(f"Backup dibuat: {backup_path}")
    return backup_path

def load_live_state():
    if LIVE_STATE_FILE.exists():
        return json.loads(LIVE_STATE_FILE.read_text())
    return {}

def save_live_state(state):
    LIVE_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    log(f"live_state.json disimpan ({len(state.get('trades', []))} trades)")

def sync_settlement(dry_run=True):
    log("=" * 60)
    log("SETTLEMENT SYNC DIMULAI")
    log(f"Mode: {'DRY RUN (preview)' if dry_run else 'EXECUTE (sync)'}")
    log("=" * 60)
    
    creds = load_creds()
    if not creds:
        log("ERROR: Tidak ada credentials.", "ERROR")
        return
    
    positions = load_positions()
    if not positions:
        log("Tidak ada posisi lokal.", "WARNING")
        return
    
    log(f"Total posisi lokal: {len(positions)}")
    
    unresolved = [p for p in positions if not p.get("resolved")]
    log(f"Posisi belum resolved: {len(unresolved)}")
    
    if not unresolved:
        log("Semua posisi sudah resolved.", "INFO")
        return
    
    if not dry_run:
        backup_file(POSITIONS_FILE)
        backup_file(LIVE_STATE_FILE)
    
    synced_count = 0
    skipped_count = 0
    
    for pos in unresolved:
        venue = pos.get("venue", "")
        market_id = pos.get("market_id", "")
        
        log(f"\nMemeriksa: {venue} - {market_id[:50]}...")
        
        try:
            exchange_positions = get_positions_detailed(venue, creds.get(venue, {}))
            found = False
            for ep in exchange_positions:
                if ep.get("title") == market_id or ep.get("ticker") == market_id:
                    found = True
                    break
            
            if not found:
                log(f"  → Tidak ada di exchange (kemungkinan sudah settle)", "SUCCESS")
                
                if dry_run:
                    log(f"  [DRY RUN] Akan update: resolved=True, pnl=0")
                    synced_count += 1
                else:
                    pos["resolved"] = True
                    pos["resolved_ts"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    pos["pnl"] = 0
                    pos["pnl_pct"] = 0
                    pos["settlement_synced"] = True
                    synced_count += 1
                    log(f"  [SYNCED] resolved=True, pnl=0")
            else:
                log(f"  → Masih aktif di exchange. Skip.", "INFO")
                skipped_count += 1
        except Exception as e:
            log(f"  → Error: {e}", "WARNING")
            skipped_count += 1
    
    if not dry_run and synced_count > 0:
        save_positions(positions)
        log(f"\n{'=' * 60}")
        log(f"SYNC SELESAI: {synced_count} posisi diupdate")
        log(f"SKIP: {skipped_count} posisi")
        log(f"Backup ada di: {BACKUP_DIR}")
        log(f"{'=' * 60}")
        
        # Update live_state.json
        log("\nMengupdate live_state.json...")
        state = load_live_state()
        trades = state.get("trades", [])
        
        synced_market_ids = [
            p.get("market_id") for p in positions 
            if p.get("settlement_synced") and p.get("resolved")
        ]
        
        updated_trades = 0
        for trade in trades:
            title = trade.get("title", "")
            for market_id in synced_market_ids:
                if market_id and market_id in title:
                    if not trade.get("resolved"):
                        trade["resolved"] = True
                        trade["pnl"] = 0
                        trade["resolved_ts"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                        updated_trades += 1
        
        if updated_trades > 0:
            state["trades"] = trades
            save_live_state(state)
            log(f"  → {updated_trades} trades diupdate")
        else:
            log("  → Tidak ada trades yang perlu diupdate")
    else:
        log(f"\n{'=' * 60}")
        log(f"DRY RUN SELESAI: {synced_count} posisi akan disync")
        log(f"SKIP: {skipped_count} posisi")
        log(f"{'=' * 60}")

def main():
    parser = argparse.ArgumentParser(description="Sync settlement data dari exchange")
    parser.add_argument("--dry-run", action="store_true", help="Preview saja")
    parser.add_argument("--execute", action="store_true", help="Jalankan sync")
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        log("ERROR: Pilih --dry-run atau --execute", "ERROR")
        sys.exit(1)
    
    sync_settlement(dry_run=args.dry_run)

if __name__ == "__main__":
    main()
