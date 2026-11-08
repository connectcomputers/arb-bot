#!/usr/bin/env python3
"""
Script untuk mengecek dan memperbaiki data P/L yang hilang.
Mencoba sinkronisasi dengan data dari exchange.
"""
import json
from pathlib import Path
import time
from datetime import datetime

DATA_DIR = Path("data")
LIVE_STATE_FILE = DATA_DIR / "live_state.json"

def load_live_state():
    if not LIVE_STATE_FILE.exists():
        print("❌ live_state.json tidak ditemukan")
        return None
    return json.loads(LIVE_STATE_FILE.read_text())

def save_live_state(data):
    LIVE_STATE_FILE.write_text(json.dumps(data, indent=2, default=str))
    print("✅ live_state.json disimpan")

def analyze_trades():
    print("=" * 70)
    print("ANALISA TRADES DI live_state.json")
    print("=" * 70)
    
    state = load_live_state()
    if not state:
        return
    
    trades = state.get("trades", [])
    print(f"\nTotal trades: {len(trades)}")
    
    # Kategorikan trades
    resolved_trades = [t for t in trades if t.get("resolved")]
    unresolved_trades = [t for t in trades if not t.get("resolved")]
    paper_trades = [t for t in trades if t.get("mode") == "paper"]
    real_trades = [t for t in trades if t.get("mode") in ["real", "real-auto", "real-micro"]]
    
    print(f"\n📊 STATISTIK:")
    print(f"  - Resolved: {len(resolved_trades)}")
    print(f"  - Unresolved: {len(unresolved_trades)}")
    print(f"  - Paper trades: {len(paper_trades)}")
    print(f"  - Real trades: {len(real_trades)}")
    
    # Cek trades dengan pnl
    trades_with_pnl = [t for t in trades if t.get("pnl") is not None and t.get("pnl") != 0]
    print(f"  - Trades dengan P/L: {len(trades_with_pnl)}")
    
    # Tampilkan sample unresolved trades
    print(f"\n SAMPLE 5 TRADES YANG BELUM RESOLVED:")
    for i, trade in enumerate(unresolved_trades[:5], 1):
        print(f"\n  [{i}] {trade.get('ts')}")
        print(f"      Mode: {trade.get('mode')}")
        print(f"      Venues: {', '.join(trade.get('venues', []))}")
        print(f"      Title: {trade.get('ta', 'N/A')[:50]}")
        print(f"      Resolved: {trade.get('resolved', False)}")
        print(f"      P/L: {trade.get('pnl', 'NOT SET')}")
    
    # Tampilkan trades dengan pnl
    if trades_with_pnl:
        print(f"\n💰 TRADES DENGAN P/L (sample):")
        for trade in trades_with_pnl[:3]:
            print(f"  - {trade.get('ts')}: P/L=${trade.get('pnl', 0):.2f}")
    
    print("\n" + "=" * 70)

def fix_missing_pnl():
    print("\n" + "=" * 70)
    print("MEMPERBAIKI DATA P/L YANG HILANG")
    print("=" * 70)
    
    state = load_live_state()
    if not state:
        return
    
    trades = state.get("trades", [])
    unresolved = [t for t in trades if not t.get("resolved")]
    
    print(f"\nDitemukan {len(unresolved)} trades yang belum resolved")
    print("\n⚠️  PERHATIAN:")
    print("   Karena bot tidak mencatat P/L saat close, kita perlu:")
    print("   1. Tandai trades lama sebagai resolved dengan P/L=0")
    print("   2. Atau input manual P/L dari history exchange")
    print("\n   Untuk saat ini, script akan tandai trades > 24 jam sebagai resolved")
    print("   dengan P/L=0 (asumsi posisi sudah close tanpa profit/loss tercatat)")
    
    confirm = input("\nLanjutkan? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ Dibatalkan")
        return
    
    now = time.time()
    fixed_count = 0
    
    for trade in unresolved:
        ts = trade.get("ts", "")
        try:
            # Parse timestamp
            trade_time = datetime.fromisoformat(ts.replace("Z", ""))
            age_hours = (now - trade_time.timestamp()) / 3600
            
            # Tandai trades > 24 jam sebagai resolved
            if age_hours > 24:
                trade["resolved"] = True
                trade["pnl"] = 0.0
                trade["pnl_pct"] = 0.0
                trade["resolved_ts"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                trade["auto_marked_resolved"] = True
                fixed_count += 1
        except Exception as e:
            print(f"  ⚠️  Error parse timestamp {ts}: {e}")
    
    if fixed_count > 0:
        print(f"\n✅ Berhasil menandai {fixed_count} trades sebagai resolved (P/L=$0)")
        save_live_state(state)
        print(f"\n NOTE: Dashboard akan menampilkan P/L=$0 untuk trades ini")
        print(f"   Untuk P/L exact, Anda perlu input manual dari history exchange")
    else:
        print("\nℹ️  Tidak ada trades yang perlu diperbaiki")

def main():
    print("\n" + "=" * 70)
    print("CHECK & FIX P/L DATA")
    print("=" * 70)
    print("\nPilih menu:")
    print("  1. Analisa trades di live_state.json")
    print("  2. Perbaiki missing P/L (tandai trades lama sebagai resolved)")
    print("  3. Keluar")
    
    choice = input("\nPilihan (1-3): ").strip()
    
    if choice == "1":
        analyze_trades()
    elif choice == "2":
        fix_missing_pnl()
    elif choice == "3":
        print(" Keluar")
        return
    else:
        print("❌ Pilihan tidak valid")

if __name__ == "__main__":
    while True:
        main()
        cont = input("\nLanjutkan? (y/n): ").strip().lower()
        if cont != 'y':
            break