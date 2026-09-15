"""Baseline saldo untuk rekonsiliasi."""
import json
from pathlib import Path

BASELINE_FILE = Path("data/baseline_saldo.json")

def save_baseline(saldo: dict):
    """Simpan saldo awal sebagai baseline."""
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps({
        "ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "saldo": saldo
    }, indent=2))

def load_baseline() -> dict:
    """Load baseline saldo."""
    if BASELINE_FILE.exists():
        try:
            return json.loads(BASELINE_FILE.read_text())
        except Exception:
            pass
    return {"ts": None, "saldo": {}}
