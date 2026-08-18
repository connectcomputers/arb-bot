"""
Limitless LIVE Tool — akun real (HMAC sesuai docs resmi).
  uv run tools/limitless_live_order.py status    # profile + saldo/posisi
  uv run tools/limitless_live_order.py markets   # market aktif
Catatan: eksekusi order butuh private key wallet (EIP-712) → fase 2.
"""
import sys
import os
import json
import hmac
import hashlib
import base64
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv
load_dotenv()

HOST = "https://api.limitless.exchange"
API_KEY = os.getenv("LIMITLESS_API_KEY", "")
API_SECRET = os.getenv("LIMITLESS_API_SECRET", "")


def auth_headers(method: str, path_with_query: str, body: str = "") -> dict:
    """HMAC-SHA256 persis protokol resmi Limitless."""
    timestamp = datetime.now(timezone.utc).isoformat()
    message = f"{timestamp}\n{method}\n{path_with_query}\n{body}"
    signature = base64.b64encode(
        hmac.new(base64.b64decode(API_SECRET),
                 message.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    return {
        "lmts-api-key": API_KEY,
        "lmts-timestamp": timestamp,
        "lmts-signature": signature,
    }


def show(title: str, r: httpx.Response):
    print(f"\n=== {title} ===")
    print("Status:", r.status_code)
    try:
        print(json.dumps(r.json(), indent=2)[:900])
    except Exception:
        print(r.text[:300])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "markets"])
    args = ap.parse_args()

    if not API_KEY or not API_SECRET:
        sys.exit("⚠ Isi LIMITLESS_API_KEY & LIMITLESS_API_SECRET di .env")

    if args.cmd == "status":
        show("PROFILE", httpx.get(
            HOST + "/profiles/me",
            headers=auth_headers("GET", "/profiles/me"), timeout=15))
        show("POSISI / SALDO", httpx.get(
            HOST + "/portfolio/positions",
            headers=auth_headers("GET", "/portfolio/positions"), timeout=15))

    if args.cmd == "markets":
        show("MARKETS ACTIVE", httpx.get(
            HOST + "/markets/active?limit=5",
            headers=auth_headers("GET", "/markets/active?limit=5"), timeout=15))


if __name__ == "__main__":
    main()