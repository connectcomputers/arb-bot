"""CEK API per venue → (ok, message)."""
import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone

import httpx


def check_polymarket(creds: dict):
    pk = creds.get("private_key", "")
    if not pk:
        return False, "private key kosong"
    try:
        from py_clob_client_v2 import ClobClient
        c = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=pk)
        c.create_or_derive_api_key()
        return True, "API VALID"
    except Exception as e:
        return False, f"TIDAK VALID: {e}"


# def check_kalshi(creds: dict):
#     key_id = creds.get("api_key_id", "")
#     pem = creds.get("private_key_pem", "")
#     if not key_id or not pem:
#         return False, "api key / pem kosong"
#     try:
#         from cryptography.hazmat.primitives import hashes, serialization
#         from cryptography.hazmat.primitives.asymmetric import padding
#         ts = str(int(time.time() * 1000))
#         path = "/trade-api/v2/portfolio/balance"
#         msg = f"{ts}GET{path}".encode()
#         key = serialization.load_pem_private_key(pem.encode(), password=None)
#         sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
#                        salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
#         r = httpx.get("https://api.kalshi.com" + path, headers={
#             "KALSHI-ACCESS-KEY": key_id,
#             "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
#             "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
#         return (True, "API VALID") if r.status_code == 200 else \
#                (False, f"TIDAK VALID: {r.status_code}")
#     except Exception as e:
#         return False, f"TIDAK VALID: {e}"

def check_kalshi(creds: dict):
    import os
    from pathlib import Path
    key_id = creds.get("api_key_id", "")
    pem = (creds.get("private_key_pem") or "").strip()
    if not key_id or not pem:
        return False, "api key / pem kosong"

    # # Terima ISI pem ATAU PATH file
    # if not pem.startswith("-----"):
    #     p = Path(os.path.expanduser(pem))
    #     if not p.exists():
    #         return False, "file pem tidak ditemukan"
    #     pem = p.read_text()

    # Terima ISI PEM (header di posisi mana pun) ATAU path file
    if "-----BEGIN" in pem:
        pem = pem[pem.find("-----BEGIN"):]          # buang sampah di depan
    else:
        p = Path(os.path.expanduser(pem))
        if not p.exists():
            return False, "file pem tidak ditemukan"
        pem = p.read_text()
    pem = pem.replace("\r\n", "\n")                  # normalisasi newline WA

    # base = (creds.get("base_url") or "").strip() or "https://api.kalshi.com"
    base = (creds.get("base_url") or "").strip() or "https://api.elections.kalshi.com"
    
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64, time, httpx
        ts = str(int(time.time() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        msg = f"{ts}GET{path}".encode()
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                       salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        r = httpx.get(base + path, headers={
            "KALSHI-ACCESS-KEY": key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts}, timeout=15)
        return (True, "API VALID") if r.status_code == 200 else \
               (False, f"TIDAK VALID: {r.status_code}")
    except Exception as e:
        return False, f"TIDAK VALID: {e}"
    
def check_limitless(creds: dict):
    key = creds.get("api_key", "")
    secret = creds.get("api_secret", "")
    if not key or not secret:
        return False, "api key / secret kosong"
    try:
        ts = datetime.now(timezone.utc).isoformat()
        path = "/profiles/me"
        message = f"{ts}\nGET\n{path}\n"
        sig = base64.b64encode(hmac.new(base64.b64decode(secret),
                       message.encode(), hashlib.sha256).digest()).decode()
        r = httpx.get("https://api.limitless.exchange" + path, headers={
            "lmts-api-key": key, "lmts-timestamp": ts,
            "lmts-signature": sig}, timeout=15)
        return (True, "API VALID") if r.status_code == 200 else \
               (False, f"TIDAK VALID: {r.status_code}")
    except Exception as e:
        return False, f"TIDAK VALID: {e}"


CHECKERS = {"polymarket": check_polymarket,
            "kalshi": check_kalshi,
            "limitless": check_limitless}


def check_venue(venue: str, creds: dict):
    fn = CHECKERS.get(venue)
    return fn(creds or {}) if fn else (False, "venue tidak dikenal")