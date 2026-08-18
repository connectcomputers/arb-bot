"""Debug autentikasi Limitless: coba varian signing, cetak alasan server."""
import sys
import os
import hmac
import hashlib
import base64
from datetime import timezone, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from app.config_store import load_creds

HOST = "https://api.limitless.exchange"
creds = load_creds().get("limitless", {})
KEY = creds.get("api_key", "")
SECRET = creds.get("api_secret", "")

if not KEY or not SECRET:
    sys.exit("⚠ Kredensial limitless belum tersimpan (isi via /setup dulu).")


def ts_plus():
    return datetime.now(timezone.utc).isoformat()


def ts_z():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ts_z_ms3():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


VARIANTS = [
    ("V1 timestamp +00:00 | secret base64-decode", ts_plus, True, True),
    ("V2 timestamp Z      | secret base64-decode", ts_z, True, True),
    ("V3 timestamp Z ms3  | secret base64-decode", ts_z_ms3, True, True),
    ("V4 timestamp Z      | secret raw string", ts_z, False, True),
    ("V5 timestamp Z      | tanpa newline akhir", ts_z, True, False),
]

path = "/profiles/me"
for name, tsfn, b64, trailing in VARIANTS:
    ts = tsfn()
    key_bytes = base64.b64decode(SECRET) if b64 else SECRET.encode()
    message = f"{ts}\nGET\n{path}\n" if trailing else f"{ts}\nGET\n{path}"
    sig = base64.b64encode(
        hmac.new(key_bytes, message.encode(), hashlib.sha256).digest()
    ).decode()
    r = httpx.get(HOST + path, headers={
        "lmts-api-key": KEY,
        "lmts-timestamp": ts,
        "lmts-signature": sig,
    }, timeout=15)
    print(f"\n=== {name} ===")
    print("status:", r.status_code)
    print("body  :", r.text[:300])
    if r.status_code == 200:
        print("\n✅ VARIAN INI YANG BENAR — catat namanya.")
        break