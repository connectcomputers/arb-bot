#!/usr/bin/env python3
"""
Script untuk patch manual P/L pada data historis.
Gunakan ini untuk mengisi P/L yang hilang dari trade masa lalu.
"""
import json
from pathlib import Path
import sys

DATA_DIR = Path("data")
POSITIONS_FILE = DATA_DIR / "positions.json"
LIVE_STATE_FILE = DATA_DIR / "live_state.json"

def patch_positions():
    print("=== PATCH POSITIONS.JSON ===")
    if not POSITIONS_FILE.exists():
        print("❌ positions.json tidak ditemukan")
        return
    
    positions = json.loads(POSITIONS_FILE.read_text())
    patched = 0
    
    for pos in positions:
        if pos.get("resolved") and (not pos.get("pnl") or pos.get("pnl") == 0):
            # Posisi resolved tapi pnl=0 atau tidak ada
            print(f"\n⚠️  Found: {pos.get('market_id', 'N/A')[:50]}")
            print(f"   Venue: {pos.get('venue')}")
            print(f"   Resolved: {pos.get('resolved')}")
            print(f"   P/L saat ini: {pos.get('pnl', 'NOT SET')}")
            
            # User bisa input P/L manual
            try:
                pnl_input = input("   Input P/L dalam USD (atau tekan Enter skip): ").strip()
                if pnl_input:
                    pnl = float(pnl_input)
                    pos["pnl"] = pnl
                    buy_price = pos.get("buy_price", 1)
                    pos["pnl_pct"] = round((pnl / buy_price) * 100, 2) if buy_price else 0
                    pos["manually_patched"] = True
                    patched += 1
                    print(f"   ✅ Patched: P/L=${pnl:.2f} ({pos['pnl_pct']}%)")
            except Exception as e:
                print(f"   ❌ Error: {e}")
    
    if patched > 0:
        # Backup
        backup = POSITIONS_FILE.with_suffix(f".json.backup")
        backup.write_text(json.dumps(positions, indent=2))
        print(f"\n💾 Backup saved: {backup}")
        
        # Save
        POSITIONS_FILE.write_text(json.dumps(positions, indent=2))
        print(f"✅ {patched} positions patched")
    else:
        print("\nℹ️  Tidak ada posisi yang perlu di-patch")

def patch_trades():
    print("\n=== PATCH LIVE_STATE.JSON (trades) ===")
    if not LIVE_STATE_FILE.exists():
        print("❌ live_state.json tidak ditemukan")
        return
    
    state = json.loads(LIVE_STATE_FILE.read_text())
    trades = state.get("trades", [])
    patched = 0
    
    for trade in trades:
        if trade.get("resolved") and (not trade.get("pnl") or trade.get("pnl") == 0):
            print(f"\n️  Found trade: {trade.get('ta', 'N/A')[:50]}")
            print(f"   Mode: {trade.get('mode')}")
            print(f"   Resolved: {trade.get('resolved')}")
            print(f"   P/L saat ini: {trade.get('pnl', 'NOT SET')}")
            
            try:
                pnl_input = input("   Input P/L dalam USD (atau tekan Enter skip): ").strip()
                if pnl_input:
                    pnl = float(pnl_input)
                    trade["pnl"] = pnl
                    trade["manually_patched"] = True
                    patched += 1
                    print(f"   ✅ Patched: P/L=${pnl:.2f}")
            except Exception as e:
                print(f"   ❌ Error: {e}")
    
    if patched > 0:
        # Backup
        backup = LIVE_STATE_FILE.with_suffix(f".json.backup")
        backup.write_text(json.dumps(state, indent=2))
        print(f"\n💾 Backup saved: {backup}")
        
        # Save
        LIVE_STATE_FILE.write_text(json.dumps(state, indent=2))
        print(f"✅ {patched} trades patched")
    else:
        print("\nℹ️  Tidak ada trades yang perlu di-patch")

if __name__ == "__main__":
    print("=" * 60)
    print("MANUAL P/L PATCHER")
    print("=" * 60)
    print("\nScript ini akan membantu Anda input P/L manual untuk")
    print("posisi/trade yang sudah resolved tapi P/L-nya $0 atau kosong.\n")
    print("💡 Tips: Cek history di Kalshi/Polymarket untuk tahu P/L exact\n")
    
    patch_positions()
    patch_trades()
    
    print("\n" + "=" * 60)
    print("DONE! Restart bot atau refresh dashboard untuk melihat perubahan.")
    print("=" * 60)