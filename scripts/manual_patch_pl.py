#!/usr/bin/env python3
"""
Script untuk patch manual P/L pada data historis.
Gunakan ini untuk mengisi P/L yang hilang dari trade masa lalu.
"""
import json
from pathlib import Path
import sys
import time

DATA_DIR = Path("data")
POSITIONS_FILE = DATA_DIR / "positions.json"
LIVE_STATE_FILE = DATA_DIR / "live_state.json"

def patch_positions():
    print("=" * 70)
    print("MANUAL P/L PATCHER - POSITIONS")
    print("=" * 70)
    
    if not POSITIONS_FILE.exists():
        print("❌ positions.json tidak ditemukan")
        return 0
    
    positions = json.loads(POSITIONS_FILE.read_text())
    patched = 0
    
    # Filter posisi yang resolved tapi pnl=0 atau tidak ada
    needs_patch = [p for p in positions if p.get("resolved") and (not p.get("pnl") or p.get("pnl") == 0)]
    
    if not needs_patch:
        print("✅ Tidak ada posisi yang perlu di-patch")
        return 0
    
    print(f"\nDitemukan {len(needs_patch)} posisi yang perlu di-patch:\n")
    
    for i, pos in enumerate(needs_patch, 1):
        print(f"[{i}] {pos.get('market_id', 'N/A')[:60]}")
        print(f"    Venue: {pos.get('venue')}")
        print(f"    Buy Price: ${pos.get('buy_price', 0):.4f}")
        print(f"    Size: ${pos.get('size', 0):.2f}")
        print(f"    Resolved: {pos.get('resolved')}")
        print(f"    P/L saat ini: ${pos.get('pnl', 0):.2f}")
        
        try:
            pnl_input = input("    Input P/L dalam USD (atau tekan Enter skip): ").strip()
            if pnl_input:
                pnl = float(pnl_input)
                pos["pnl"] = pnl
                buy_price = pos.get("buy_price", 1)
                pos["pnl_pct"] = round((pnl / buy_price) * 100, 2) if buy_price else 0
                pos["manually_patched"] = True
                pos["patched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                patched += 1
                print(f"    ✅ Patched: P/L=${pnl:.2f} ({pos['pnl_pct']}%)\n")
            else:
                print(f"    ⏭️  Skip\n")
        except Exception as e:
            print(f"    ❌ Error: {e}\n")
    
    if patched > 0:
        # Backup
        backup = POSITIONS_FILE.with_suffix(f".json.backup.{int(time.time())}")
        backup.write_text(json.dumps(positions, indent=2))
        print(f"💾 Backup saved: {backup}")
        
        # Save
        POSITIONS_FILE.write_text(json.dumps(positions, indent=2))
        print(f"✅ {patched} positions berhasil di-patch")
    
    return patched

def patch_trades():
    print("\n" + "=" * 70)
    print("MANUAL P/L PATCHER - TRADES (live_state.json)")
    print("=" * 70)
    
    if not LIVE_STATE_FILE.exists():
        print("❌ live_state.json tidak ditemukan")
        return 0
    
    state = json.loads(LIVE_STATE_FILE.read_text())
    trades = state.get("trades", [])
    patched = 0
    
    # Filter trades yang resolved tapi pnl=0
    needs_patch = [t for t in trades if t.get("resolved") and (not t.get("pnl") or t.get("pnl") == 0)]
    
    if not needs_patch:
        print("✅ Tidak ada trades yang perlu di-patch")
        return 0
    
    print(f"\nDitemukan {len(needs_patch)} trades yang perlu di-patch:\n")
    
    for i, trade in enumerate(needs_patch, 1):
        print(f"[{i}] {trade.get('ta', 'N/A')[:60]}")
        print(f"    Mode: {trade.get('mode')}")
        print(f"    Venues: {', '.join(trade.get('venues', []))}")
        print(f"    Resolved: {trade.get('resolved')}")
        print(f"    P/L saat ini: ${trade.get('pnl', 0):.2f}")
        
        try:
            pnl_input = input("    Input P/L dalam USD (atau tekan Enter skip): ").strip()
            if pnl_input:
                pnl = float(pnl_input)
                trade["pnl"] = pnl
                trade["manually_patched"] = True
                trade["patched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                patched += 1
                print(f"    ✅ Patched: P/L=${pnl:.2f}\n")
            else:
                print(f"    ️  Skip\n")
        except Exception as e:
            print(f"    ❌ Error: {e}\n")
    
    if patched > 0:
        # Backup
        backup = LIVE_STATE_FILE.with_suffix(f".json.backup.{int(time.time())}")
        backup.write_text(json.dumps(state, indent=2))
        print(f"💾 Backup saved: {backup}")
        
        # Save
        LIVE_STATE_FILE.write_text(json.dumps(state, indent=2))
        print(f"✅ {patched} trades berhasil di-patch")
    
    return patched

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("MANUAL P/L PATCHER")
    print("=" * 70)
    print("\nScript ini akan membantu Anda input P/L manual untuk")
    print("posisi/trade yang sudah resolved tapi P/L-nya $0 atau kosong.\n")
    print(" Tips: Cek history di Kalshi/Polymarket untuk tahu P/L exact\n")
    
    pos_patched = patch_positions()
    trades_patched = patch_trades()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Positions patched: {pos_patched}")
    print(f"Trades patched: {trades_patched}")
    print(f"Total patched: {pos_patched + trades_patched}")
    print("\n✅ DONE! Refresh dashboard untuk melihat perubahan.")
    print("=" * 70 + "\n")