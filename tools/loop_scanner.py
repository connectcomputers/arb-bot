"""
Loop Scanner — Minggu 8.2.
Menjalankan scan_cycle() setiap 60 detik, output ringkas ke terminal + log file.

Penggunaan:
  uv run tools/loop_scanner.py           # foreground, Ctrl+C untuk berhenti
  uv run tools/loop_scanner.py --quiet   # hanya log ke file, tidak ke terminal

Atau via systemd user service (lihat README_LOOP.md).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import argparse
import fcntl
import json
import signal
import time
from datetime import datetime
from pathlib import Path as P

from tools.live_opportunity import scan_cycle

LOOP_INTERVAL_SEC = 60
LOCK_FILE = P("/tmp/arb-bot-loop.lock")
LOG_FILE = P("data/loop.log")

# === FLAG GRACEFUL SHUTDOWN ===
shutdown_requested = False


def signal_handler(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    print(f"\n[{datetime.now():%H:%M:%S}] 🛑 Received signal {signum}, shutting down gracefully...")


def acquire_lock():
    """Mencegah multiple instance berjalan bersamaan."""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(time.time()))
        lock_fd.flush()
        return lock_fd
    except (IOError, OSError):
        print(f"❌ Instance lain sudah berjalan (lock file: {LOCK_FILE}). Keluar.")
        sys.exit(1)


def append_log(entry: dict):
    """Append satu baris JSON ke log file (rotasi sederhana: truncate kalau >100MB)."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Rotasi sederhana: kalau file > 100MB, backup dan buat baru
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 100_000_000:
        backup = LOG_FILE.with_suffix(f".log.{int(time.time())}")
        LOG_FILE.rename(backup)
    
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


async def run_loop(quiet: bool):
    """Main loop — scan setiap 60 detik sampai shutdown diminta."""
    cycle_num = 0
    
    print(f"[{datetime.now():%H:%M:%S}] 🔄 Loop dimulai (interval {LOOP_INTERVAL_SEC}s)")
    print(f"[{datetime.now():%H:%M:%S}] 📁 Log file: {LOG_FILE}")
    print(f"[{datetime.now():%H:%M:%S}] ⌨️  Tekan Ctrl+C untuk berhenti\n")
    
    while not shutdown_requested:
        cycle_num += 1
        cycle_start = time.time()
        
        try:
            result = await scan_cycle(quiet=True)
            
            # Build ringkasan
            execute_count = sum(1 for _, sig, _ in result.decisions if sig.execute)
            wait_count = sum(1 for _, sig, _ in result.decisions if not sig.execute)
            paper_count = sum(p for _, _, p in result.decisions)
            
            # Ringkasan satu baris
            summary = (f"[{datetime.now():%H:%M:%S}] "
                       f"#{cycle_num:04d} | "
                       f"Poly:{result.poly_fetched:02d} Kalshi:{result.kalshi_fetched:02d} | "
                       f"🔒{len(result.locked)} | "
                       f"🟢{execute_count} 🟡{wait_count} 📝{paper_count} | "
                       f"skip:{len(result.skipped)}")
            
            if result.errors:
                summary += f" | ⚠{len(result.errors)}"
            
            if not quiet:
                print(summary)
            
            # Log ke file (selalu)
            log_entry = {
                "cycle": cycle_num,
                "timestamp": datetime.now().isoformat(),
                "poly": result.poly_fetched,
                "kalshi": result.kalshi_fetched,
                "locked": len(result.locked),
                "execute": execute_count,
                "wait": wait_count,
                "paper": paper_count,
                "skipped": len(result.skipped),
                "errors": result.errors,
            }
            
            # Detail keputusan (jika ada)
            if result.decisions:
                log_entry["decisions"] = []
                for lock, sig, papers in result.decisions:
                    log_entry["decisions"].append({
                        "key": str(lock.key),
                        "direction": sig.direction,
                        "pi": str(sig.pi),
                        "execute": sig.execute,
                        "paper": papers,
                    })
            
            append_log(log_entry)
            
            # Highlight peluang
            if execute_count > 0:
                print(f"  [bold green]   🎯 {execute_count} EKSEKUSI terdeteksi![/bold green]")
        
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[{datetime.now():%H:%M:%S}] ❌ Error di cycle {cycle_num}: {e}")
            append_log({
                "cycle": cycle_num,
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            })
        
        # Sleep dengan cek shutdown tiap 1 detik (responsif Ctrl+C)
        elapsed = time.time() - cycle_start
        sleep_remaining = max(0, LOOP_INTERVAL_SEC - elapsed)
        
        # Sleep dalam chunk 1 detik agar Ctrl+C responsif
        sleep_end = time.time() + sleep_remaining
        while time.time() < sleep_end and not shutdown_requested:
            await asyncio.sleep(1)
    
    print(f"\n[{datetime.now():%H:%M:%S}] ✅ Loop berhenti setelah {cycle_num} siklus.")


def main():
    parser = argparse.ArgumentParser(description="Loop scanner arbitrase")
    parser.add_argument("--quiet", action="store_true",
                        help="Jangan print ke terminal, hanya log ke file")
    parser.add_argument("--interval", type=int, default=60,
                        help="Interval antar scan dalam detik (default 60)")
    args = parser.parse_args()
    
    global LOOP_INTERVAL_SEC
    LOOP_INTERVAL_SEC = args.interval
    
    # Setup signal handlers untuk graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # systemctl stop
    
    # Acquire lock (cegah multiple instance)
    lock_fd = acquire_lock()
    
    try:
        asyncio.run(run_loop(quiet=args.quiet))
    finally:
        # Release lock
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()