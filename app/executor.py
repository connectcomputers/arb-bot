# /app/executor.py
"""Executor S-Final: order real mikro per venue."""
import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
# import httpx
import uuid as _uuid
import httpx
import hashlib
import asyncio
import threading

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from eth_account import Account

from datetime import datetime, timezone
from eth_account import Account

EXEC_LOG = Path("data") / "exec_log.jsonl"
APPROVED_FLAG = Path("data") / "lim_approved.json"

# EXEC_LOG = Path("data") / "exec_log.jsonl"

SERIES_CANDIDATES = ["KXMLB", "KXNFL", "KXNBA", "KXNHL", "KXELEC", "KXPOL",
                     "KXCPI", "KXFED", "KXBTC", "KXETH", "KXSPX", "KXGOLD"]

# USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71bF37bb0B8BD"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
RPC_BASE = "https://mainnet.base.org"
APPROVED_FLAG = Path("data") / "lim_approved.json"


KALSHI_HOST = "https://external-api.kalshi.com"
KALSHI_ROOT = "/trade-api/v2"

# async def _lim_server_wallet_async(creds, usd, dry=False, ticker=None):
#     from limitless_sdk import Client, HMACCredentials
#     from limitless_sdk.types import Side, OrderType

#     profile_raw = str(
#         creds.get("smart_wallet_profile_id") or ""
#     ).strip()

#     if not profile_raw.isdigit():
#         return (
#             False,
#             "Limitless Managed Wallet: "
#             "smart_wallet_profile_id harus numeric"
#         )

#     profile_id = int(profile_raw)

#     client = Client(
#         base_url="https://api.limitless.exchange",
#         hmac_credentials=HMACCredentials(
#             token_id=creds["api_key"],
#             secret=creds["api_secret"],
#         ),
#     )

#     try:
#         # Ambil market
#         if ticker:
#             slug = ticker
#         else:
#             r = httpx.get(
#                 "https://api.limitless.exchange/markets/active",
#                 params={"limit": 25},
#                 timeout=15,
#             )
#             r.raise_for_status()

#             m = next(
#                 (
#                     x for x in r.json().get("data", [])
#                     if x.get("prices")
#                     and len(x["prices"]) == 2
#                 ),
#                 None,
#             )

#             if not m:
#                 return False, "Limitless: tidak ada market aktif"

#             slug = m["slug"]

#         market = await client.markets.get_market(slug)

#         token_id = str(market.tokens.yes)

#         # Pastikan server-wallet memang siap trading.
#         allowances = await client.partner_accounts.check_allowances(
#             profile_id
#         )

#         if not allowances.ready:
#             return (
#                 False,
#                 "Limitless Managed Wallet belum READY: "
#                 f"profile={profile_id}; "
#                 f"summary={allowances.summary}"
#             )

#         if dry:
#             return (
#                 True,
#                 "[DRY] Limitless Managed Wallet READY "
#                 f"profile={profile_id} "
#                 f"market={market.slug} "
#                 f"token={token_id}"
#             )

#         # FOK BUY = spend USD amount.
#         response = await client.delegated_orders.create_order(
#             token_id=token_id,
#             side=Side.BUY,
#             order_type=OrderType.FOK,
#             market_slug=market.slug,
#             on_behalf_of=profile_id,
#             maker_amount=float(usd),
#         )

#         matches = getattr(response, "maker_matches", None) or []

#         return (
#             True,
#             f"Limitless Managed BUY ${usd:.2f} "
#             f"profile={profile_id} "
#             f"market={market.slug} "
#             f"matches={len(matches)}"
#         )

#     except Exception as e:
#         return False, f"Limitless Managed error: {e}"

#     finally:
#         await client.close()

# ============================================================
# LIMITLESS EXECUTION
# ============================================================
def _run_async(coro):
    """
    Jalankan coroutine dari kode sync.

    Penting:
    FastAPI endpoint Anda adalah async, sementara engine/executor
    saat ini synchronous.

    asyncio.run() langsung bisa gagal jika sudah ada event loop.
    Karena itu jika event loop sedang aktif, coroutine dijalankan
    di thread terpisah.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result = {}
    error = {}

    def runner():
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            error["value"] = exc

    t = threading.Thread(
        target=runner,
        daemon=True,
    )

    t.start()
    t.join()

    if "value" in error:
        raise error["value"]

    return result.get("value")

def _limitless_wallet_mode(creds):
    """
    Normalisasi mode wallet.

    Internal value:
      smartWallet = Wallet Limitless / server wallet
      eoa         = Wallet Pribadi
    """
    mode = str(
        creds.get("wallet_mode") or "smartWallet"
    ).strip()

    aliases = {
        "wallet_limitless": "smartWallet",
        "limitless": "smartWallet",
        "serverWallet": "smartWallet",
        "server_wallet": "smartWallet",

        "wallet_pribadi": "eoa",
        "personal": "eoa",
        "private": "eoa",
    }

    return aliases.get(mode, mode)

def _validate_limitless_common(creds):
    api_key = str(
        creds.get("api_key") or ""
    ).strip()

    api_secret = str(
        creds.get("api_secret") or ""
    ).strip()

    if not api_key:
        return False, "Limitless: API Key kosong"

    if not api_secret:
        return False, "Limitless: API Secret kosong"

    return True, ""

async def _lim_server_wallet_async(
    creds,
    usd,
    dry=False,
    ticker=None,
):
    """
    Limitless Managed Wallet / Server Wallet.

    Tidak menggunakan private key.

    Flow:
      API key + HMAC
        ↓
      delegated child profile
        ↓
      check allowances
        ↓
      FOK delegated order
    """

    try:

        from limitless_sdk import (
            Client,
            HMACCredentials,
        )

        from limitless_sdk.types import (
            Side,
            OrderType,
        )

    except Exception as e:

        return (
            False,
            "Limitless Managed Wallet: "
            f"limitless-sdk tidak tersedia: {e}",
        )


    # profile_raw = str(
    #     creds.get(
    #         "smart_wallet_profile_id"
    #     ) or ""
    # ).strip()

    profile_raw = str(
        creds.get("smart_wallet_profile_id")
        or creds.get("delegated_profile_id")
        or ""
    ).strip()

    if not profile_raw.isdigit():

        return (
            False,
            "Limitless Managed Wallet: "
            "smart_wallet_profile_id harus numeric. "
            "Gunakan profile ID child server-wallet "
            "yang dibuat melalui delegated-signing.",
        )


    profile_id = int(profile_raw)


    api_key = str(
        creds.get("api_key") or ""
    ).strip()

    api_secret = str(
        creds.get("api_secret") or ""
    ).strip()


    if not api_key:
        return False, "Limitless: API Key kosong"

    if not api_secret:
        return False, "Limitless: API Secret kosong"


    client = None


    try:

        client = Client(
            base_url="https://api.limitless.exchange",
            hmac_credentials=HMACCredentials(
                token_id=api_key,
                secret=api_secret,
            ),
        )


        # ----------------------------------------------------
        # MARKET
        # ----------------------------------------------------

        if ticker:

            slug = str(ticker).strip()

        else:

            r = httpx.get(
                "https://api.limitless.exchange/markets/active",
                params={"limit": 25},
                timeout=15,
            )

            r.raise_for_status()

            markets = (
                r.json().get("data", [])
            )

            m = next(
                (
                    x for x in markets
                    if x.get("prices")
                    and len(x["prices"]) == 2
                ),
                None,
            )

            if not m:

                return (
                    False,
                    "Limitless: "
                    "tidak ada market aktif",
                )

            slug = m["slug"]


        market = (
            await client.markets.get_market(slug)
        )


        token_id = str(
            market.tokens.yes
        )


        # ----------------------------------------------------
        # ALLOWANCE / SERVER-WALLET READINESS
        # ----------------------------------------------------

        allowances = (
            await client.partner_accounts
            .check_allowances(profile_id)
        )


        if not allowances.ready:

            summary = getattr(
                allowances,
                "summary",
                str(allowances),
            )

            return (
                False,
                "Limitless Managed Wallet "
                "belum READY: "
                f"profile={profile_id}; "
                f"summary={summary}",
            )


        # ----------------------------------------------------
        # DRY RUN
        #
        # Penting:
        # sampai titik ini hanya read/check.
        # Tidak ada create_order.
        # ----------------------------------------------------

        if dry:

            return (
                True,
                "[DRY] Limitless Managed Wallet READY "
                f"profile={profile_id} "
                f"market={market.slug} "
                f"token={token_id} "
                f"amount=${float(usd):.2f}",
            )


        # ----------------------------------------------------
        # REAL ORDER
        # ----------------------------------------------------

        response = (
            await client.delegated_orders.create_order(
                token_id=token_id,
                side=Side.BUY,
                order_type=OrderType.FOK,
                market_slug=market.slug,
                on_behalf_of=profile_id,
                maker_amount=float(usd),
            )
        )


        matches = (
            getattr(
                response,
                "maker_matches",
                None,
            )
            or []
        )


        # FOK tanpa match bukan order berhasil.
        if not matches:

            order_obj = getattr(
                response,
                "order",
                None,
            )

            status = getattr(
                order_obj,
                "status",
                None,
            )

            return (
                False,
                "Limitless Managed Wallet: "
                "FOK tidak mendapatkan match"
                + (
                    f"; status={status}"
                    if status
                    else ""
                ),
            )


        order_obj = getattr(
            response,
            "order",
            None,
        )

        order_id = getattr(
            order_obj,
            "id",
            None,
        )


        return (
            True,
            "Limitless Managed BUY "
            f"${float(usd):.2f} "
            f"profile={profile_id} "
            f"market={market.slug} "
            f"matches={len(matches)}"
            + (
                f" order_id={order_id}"
                if order_id
                else ""
            ),
        )


    except Exception as e:

        return (
            False,
            "Limitless Managed error: "
            f"{type(e).__name__}: {e}",
        )


    finally:

        if client is not None:

            try:
                await client.close()
            except Exception:
                pass


# ============================================================

def _k_sign(pem, ts, method, path, body=""):
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    sig = key.sign(f"{ts}{method}{path}{body}".encode(),
                   padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                               salt_length=padding.PSS.DIGEST_LENGTH),
                   hashes.SHA256())
    return base64.b64encode(sig).decode()


def _k_headers(creds, method, path, body=""):
    ts = str(int(time.time() * 1000))
    return {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
            "KALSHI-ACCESS-SIGNATURE": _k_sign(
                creds.get("private_key_pem", ""), ts, method, path, body),
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"}


# def _k_market():
#     with httpx.Client(timeout=10) as client:
#         r = client.get(KALSHI_HOST + KALSHI_ROOT + "/markets",
#                        params={"status": "open", "limit": 100})
#         r.raise_for_status()
#     for m in r.json().get("markets", []):
#         yes = float(m.get("yes_ask") or 0) / 100
#         if 0.30 <= yes <= 0.70 and m.get("ticker"):
#             return {"ticker": m["ticker"], "yes": yes}
#     return None

def _k_price(m):
    for f in ("yes_ask_dollars", "last_price_dollars", "yes_bid_dollars",
              "yes_ask", "last_price", "yes_bid"):
        v = m.get(f)
        if v not in (None, "", 0, "0"):
            v = float(v)
            return v / 100 if v > 1 else v
    return 0.0

def _k_get_market(creds, ticker):
    path = KALSHI_ROOT + "/markets/" + ticker
    for host, hdr in ((KALSHI_HOST, _k_headers(creds, "GET", path)),
                      ("https://api.elections.kalshi.com", None)):
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(host + path, headers=hdr)
                r.raise_for_status()
            m = r.json().get("market") or {}
            if m.get("ticker"):
                return {"ticker": m["ticker"], "yes": _k_price(m) or 0.50}
        except Exception:
            continue
    return None

def _k_market(creds, ticker=None):
    if ticker:
        return _k_get_market(creds, ticker)      # ← endpoint tunggal, terbukti 200
    for host, hdr in ((KALSHI_HOST, _k_headers(creds, "GET", KALSHI_ROOT + "/markets")),
                      ("https://api.elections.kalshi.com", None)):
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(host + KALSHI_ROOT + "/markets",
                               params={"status": "open", "limit": 500}, headers=hdr)
                r.raise_for_status()
            for m in r.json().get("markets", []):
                yes = _k_price(m)
                if 0.30 <= yes <= 0.70 and m.get("ticker"):
                    return {"ticker": m["ticker"], "yes": yes}
        except Exception:
            continue
    return None

def _rpc(method, params=None):
    r = httpx.post(RPC_BASE, json={"jsonrpc": "2.0", "id": 1,
                   "method": method, "params": params or []}, timeout=15)
    return r.json().get("result")


# def _lim_hmac(creds, method, path):
#     ts = datetime.now(timezone.utc).isoformat()
#     msg = f"{ts}\n{method}\n{path}\n"
#     sig = base64.b64encode(hmac.new(base64.b64decode(creds["api_secret"]),
#                    msg.encode(), hashlib.sha256).digest()).decode()
#     return {"lmts-api-key": creds["api_key"],
#             "lmts-timestamp": ts, "lmts-signature": sig}

def _lim_hmac(creds, method, path, body=None):
    ts = datetime.now(timezone.utc).isoformat()
    if body:
        msg = f"{ts}\n{method}\n{path}\n{body}"
    else:
        msg = f"{ts}\n{method}\n{path}\n"
    sig = base64.b64encode(hmac.new(base64.b64decode(creds["api_secret"]),
                   msg.encode(), hashlib.sha256).digest()).decode()
    return {"lmts-api-key": creds["api_key"],
            "lmts-timestamp": ts, "lmts-signature": sig,
            "Content-Type": "application/json"}

# def _lim_switch_eoa(creds):
#     r = httpx.put("https://api.limitless.exchange/profiles",
#                   json={"tradeWalletOption": "eoa"},
#                   headers=_lim_hmac(creds, "PUT", "/profiles"), timeout=15)
#     return r.status_code

def _lim_switch_eoa(creds):
    body = json.dumps({"tradeWalletOption": "eoa"}, separators=(",", ":"))
    r = httpx.put("https://api.limitless.exchange/profiles",
                  content=body,
                  headers=_lim_hmac(creds, "PUT", "/profiles", body), timeout=15)
    return r.status_code

def _lim_approve(pk, spender):
    acct = Account.from_key(pk)
    nonce = int(_rpc("eth_getTransactionCount", [acct.address, "latest"]), 16)
    gp = int(_rpc("eth_gasPrice"), 16)
    data = ("095ea7b3" + spender[2:].rjust(64, "0")
            + format(2**256 - 1, "x").rjust(64, "0"))
    tx = {"chainId": 8453, "nonce": nonce, "to": USDC_BASE,
          "data": "0x" + data, "gas": 120000, "gasPrice": gp * 2}
    signed = Account.sign_transaction(tx, pk)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    return _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])

# def exec_limitless(creds, usd=2, dry=False, ticker=None):
#     pk = (creds.get("wallet_pk") or "").strip()
#     pk_hex = pk[2:] if pk.lower().startswith("0x") else pk
#     if len(pk_hex) != 64 or not set(pk_hex) <= set("0123456789abcdefABCDEF"):
#         return (False, f"Limitless: field Wallet Private Key berisi "
#                        f"{len(pk_hex)} hex (ALAMAT wallet) — butuh PRIVATE KEY "
#                        f"64 hex; minta re-ekspor dari wallet")
#     # _lim_switch_eoa(creds)   # ← BIARKAN DIKOMENTAR (sudah Anda lakukan)

# def exec_limitless(creds, usd=2, dry=False, ticker=None):
#     mode = creds.get("wallet_mode", "eoa")
#     if mode == "smartWallet":
#         return _exec_limitless_server_wallet(creds, usd, dry)
#     else:
#         # Jalur EOA — inline logika lama
#         pk = (creds.get("wallet_pk") or "").strip()
#         pk_hex = pk[2:] if pk.lower().startswith("0x") else pk
#         if len(pk_hex) != 64 or not set(pk_hex) <= set("0123456789abcdefABCDEF"):
#             return (False, f"Limitless: field Wallet Private Key berisi "
#                            f"{len(pk_hex)} hex — butuh PRIVATE KEY 64 hex")
#         # (sisanya = logika EOA yang sudah ada)

# def exec_limitless(creds, usd=2, dry=False, ticker=None):
#     mode = creds.get("wallet_mode", "smartWallet")

#     if mode == "smartWallet":
#         return _exec_limitless_server_wallet(
#             creds, usd, dry, ticker
#         )

#     if mode == "eoa":
#         return _exec_limitless_eoa(
#             creds, usd, dry, ticker
#         )

#     return False, f"Limitless: wallet_mode tidak dikenal: {mode}"

#     r = httpx.get("https://api.limitless.exchange/markets/active",
#                   params={"limit": 25}, timeout=15)
#     m = next((x for x in r.json().get("data", [])
#               if x.get("prices") and len(x["prices"]) == 2), None)
#     if not m:
#         return False, "tidak ada market limitless"
#     d = httpx.get(f"https://api.limitless.exchange/markets/{m['slug']}",
#                   timeout=15).json().get("data", {})
#     exchange = (d.get("venue") or {}).get("exchange") or d.get("exchangeAddress")
#     token_id = int((d.get("tokenIds") or [0])[0] or d.get("yesTokenId") or 0)
    
#     pk = (creds.get("wallet_pk") or "").strip()
#     pk_hex = pk[2:] if pk.lower().startswith("0x") else pk
#     if len(pk_hex) != 64 or not set(pk_hex) <= set("0123456789abcdefABCDEF"):
#         return (False, f"Limitless: field Wallet Private Key berisi "
#                        f"{len(pk_hex)} hex (ALAMAT wallet) — butuh PRIVATE KEY "
#                        f"64 hex; minta re-ekspor dari wallet")
        
#     acct = Account.from_key(pk)
#     if not APPROVED_FLAG.exists():
#         _lim_approve(pk, exchange)
#         APPROVED_FLAG.write_text(json.dumps({"ts": time.time()}))
#     maker_amount = int(usd * 1e6)
#     order = {"salt": int(time.time() * 1000), "maker": acct.address,
#              "signer": acct.address,
#              "taker": "0x0000000000000000000000000000000000000000",
#              "tokenId": token_id, "makerAmount": maker_amount,
#              "takerAmount": 1, "expiration": 0, "nonce": 0,
#              "feeRateBps": 0, "side": 0, "signatureType": 0}
#     domain = {"name": "Limitless CTF Exchange", "version": "1",
#               "chainId": 8453, "verifyingContract": exchange}
#     types = {"Order": [
#         {"name": "salt", "type": "uint256"}, {"name": "maker", "type": "address"},
#         {"name": "signer", "type": "address"}, {"name": "taker", "type": "address"},
#         {"name": "tokenId", "type": "uint256"},
#         {"name": "makerAmount", "type": "uint256"},
#         {"name": "takerAmount", "type": "uint256"},
#         {"name": "expiration", "type": "uint256"}, {"name": "nonce", "type": "uint256"},
#         {"name": "feeRateBps", "type": "uint256"}, {"name": "side", "type": "uint8"},
#         {"name": "signatureType", "type": "uint8"}]}
#     sig = Account.sign_typed_data(pk, domain, types, order)
#     if dry:
#         return True, f"[DRY] limitless BUY {m['title'][:40]} sig={sig.signature.hex()[:20]}…"
#     # ro = httpx.post("https://api.limitless.exchange/orders",
#     #                 json={**order, "signature": sig.signature.hex(),
#     #                       "market": m["slug"]},
#     #                 headers=_lim_hmac(creds, "POST", "/orders"), timeout=15)

#     order_payload = {**order, "signature": sig.signature.hex(),
#                      "market": m["slug"]}
#     order_body = json.dumps(order_payload, separators=(",", ":"))
#     ro = httpx.post("https://api.limitless.exchange/orders",
#                     content=order_body,
#                     headers=_lim_hmac(creds, "POST", "/orders", order_body),
#                     timeout=15)
    
#     _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "venue": "limitless",
#           "status": ro.status_code, "body": ro.text[:150]})
#     if ro.status_code in (200, 201):
#         return True, f"BUY {usd} USDC :: {m['title'][:40]}"
#     return False, f"limitless {ro.status_code}: {ro.text[:120]}"

# dari chatgpt
def exec_limitless(
    creds,
    usd=2,
    dry=False,
    ticker=None,
):
    """
    Compatibility layer utama Limitless.

    wallet_mode:
        smartWallet -> Wallet Limitless
        eoa         -> Wallet Pribadi
    """

    ok, msg = _validate_limitless_common(
        creds
    )

    if not ok:
        return False, msg


    mode = _limitless_wallet_mode(
        creds
    )


    if mode == "smartWallet":

        return _exec_limitless_server_wallet(
            creds,
            usd,
            dry=dry,
            ticker=ticker,
        )


    if mode == "eoa":

        return _exec_limitless_eoa(
            creds,
            usd,
            dry=dry,
            ticker=ticker,
        )


    return (
        False,
        "Limitless: wallet_mode tidak dikenal: "
        f"{mode}. Gunakan smartWallet atau eoa.",
    )

# def _exec_limitless_server_wallet(creds, usd, dry):
#     """Order via server wallet (delegated signing) - tanpa private key"""
#     # Switch ke smartWallet (aman diulang, idempotent)
#     body_switch = json.dumps({
#         "tradeWalletOption": "smartWallet",
#         "smartWallet": "0x7F1A65944C8a3A3cb44B7286eeb07dF0e834f897",
#         "embeddedAccount": "0xC1cDA2CC554c84455E1f29A506972C8d6b1872B6"
#     }, separators=(",", ":"))
# def _exec_limitless_server_wallet(creds, usd, dry, ticker=None):
#     return asyncio.run(
#         _lim_server_wallet_async(
#             creds,
#             usd,
#             dry=dry,
#             ticker=ticker,
#         )
#     )
#     httpx.put("https://api.limitless.exchange/profiles",
#               content=body_switch,
#               headers=_lim_hmac(creds, "PUT", "/profiles", body_switch),
#               timeout=15)
    
#     # Ambil market
#     r = httpx.get("https://api.limitless.exchange/markets/active",
#                   params={"limit": 25}, timeout=15)
#     m = next((x for x in r.json().get("data", [])
#               if x.get("prices") and len(x["prices"]) == 2), None)
#     if not m:
#         return False, "tidak ada market limitless"
    
#     # PLACEHOLDER format order server wallet (akan diisi hasil probe)
#     # Saat ini kirim sinyal "menunggu kalibrasi format"
#     if dry:
#         return True, f"[DRY] limitless server wallet BUY {usd} :: {m['slug']}"
    
#     # Format yang akan kita pakai (update setelah probe):
#     order = {"slug": m["slug"], "amount": usd}  # ← ganti setelah probe valid
#     order_body = json.dumps(order, separators=(",", ":"))
    
#     ro = httpx.post("https://api.limitless.exchange/orders",
#                     content=order_body,
#                     headers=_lim_hmac(creds, "POST", "/orders", order_body),
#                     timeout=15)
#     if ro.status_code in (200, 201):
#         return True, f"BUY {usd} USDC (server wallet) :: {m['slug']}"
#     return False, f"limitless server {ro.status_code}: {ro.text[:120]}"

# dari chatgpt
def _exec_limitless_server_wallet(
    creds,
    usd,
    dry=False,
    ticker=None,
):

    return _run_async(
        _lim_server_wallet_async(
            creds,
            usd,
            dry=dry,
            ticker=ticker,
        )
    )

async def _lim_eoa_async(
    creds,
    usd,
    dry=False,
    ticker=None,
):
    """
    Limitless order menggunakan wallet pribadi EOA.

    Private key HARUS:
        0x + 64 hex

    Order dibuat melalui Limitless Python SDK,
    bukan payload /orders manual yang sebelumnya belum
    terbukti kompatibel.
    """

    pk = str(
        creds.get("wallet_pk") or ""
    ).strip()


    pk_hex = (
        pk[2:]
        if pk.lower().startswith("0x")
        else pk
    )


    # --------------------------------------------------------
    # VALIDATE PRIVATE KEY
    # --------------------------------------------------------

    if (
        len(pk_hex) != 64
        or not pk_hex
        or not set(pk_hex)
            <= set(
                "0123456789abcdefABCDEF"
            )
    ):

        return (
            False,
            "Limitless Wallet Pribadi: "
            "wallet_pk harus PRIVATE KEY "
            "0x + 64 hex. "
            f"Saat ini {len(pk_hex)} hex.",
        )


    try:

        acct = Account.from_key(pk)

    except Exception as e:

        return (
            False,
            "Limitless Wallet Pribadi: "
            f"private key tidak valid: {e}",
        )


    # --------------------------------------------------------
    # SWITCH LIMITLESS PROFILE KE EOA
    #
    # HANYA REAL.
    #
    # dry=True tidak boleh mengubah profile.
    # --------------------------------------------------------

    if not dry:

        status = _lim_switch_eoa(
            creds
        )

        if status < 200 or status >= 300:

            return (
                False,
                "Limitless EOA: gagal "
                "switch trade wallet ke EOA; "
                f"HTTP {status}",
            )


    # --------------------------------------------------------
    # SDK
    # --------------------------------------------------------

    try:

        from limitless_sdk.api import (
            HttpClient,
        )

        from limitless_sdk.markets import (
            MarketFetcher,
        )

        from limitless_sdk.orders import (
            OrderClient,
        )

        from limitless_sdk.types import (
            Side,
            OrderType,
        )

    except Exception as e:

        return (
            False,
            "Limitless EOA: "
            f"limitless-sdk tidak tersedia: {e}",
        )


    api_key = str(
        creds.get("api_key") or ""
    ).strip()


    if not api_key:

        return (
            False,
            "Limitless EOA: API Key kosong",
        )


    http_client = None


    try:

        http_client = HttpClient(
            base_url="https://api.limitless.exchange",
            api_key=api_key,
        )


        # ----------------------------------------------------
        # MARKET
        # ----------------------------------------------------

        market_fetcher = (
            MarketFetcher(http_client)
        )


        if ticker:

            slug = str(ticker).strip()

        else:

            markets = (
                await market_fetcher
                .get_active_markets(
                    {
                        "limit": 25,
                    }
                )
            )

            rows = getattr(
                markets,
                "data",
                None,
            )

            if rows is None and isinstance(
                markets,
                dict,
            ):

                rows = markets.get(
                    "data",
                    [],
                )

            rows = rows or []


            m = next(
                (
                    x for x in rows
                    if x.get("prices")
                    and len(x["prices"]) == 2
                ),
                None,
            )


            if not m:

                return (
                    False,
                    "Limitless EOA: "
                    "tidak ada market aktif",
                )


            slug = m["slug"]


        market = (
            await market_fetcher
            .get_market(slug)
        )


        token_id = str(
            market.tokens.yes
        )


        # ----------------------------------------------------
        # DRY
        #
        # Tidak approve.
        # Tidak POST order.
        # Tidak send transaction.
        # Hanya validasi key + market.
        # ----------------------------------------------------

        if dry:

            return (
                True,
                "[DRY] Limitless Wallet Pribadi "
                f"EOA={acct.address} "
                f"market={market.slug} "
                f"token={token_id} "
                f"amount=${float(usd):.2f}",
            )


        # ----------------------------------------------------
        # APPROVAL
        #
        # One-time approval.
        #
        # Jangan pernah dilakukan saat dry=True.
        # ----------------------------------------------------

        exchange = getattr(
            getattr(
                market,
                "venue",
                None,
            ),
            "exchange",
            None,
        )


        if not exchange:

            return (
                False,
                "Limitless EOA: "
                "venue.exchange tidak ditemukan "
                f"untuk market {market.slug}",
            )


        # Gunakan flag per wallet + exchange,
        # bukan satu flag global.
        approval_key = (
            f"{acct.address.lower()}:"
            f"{str(exchange).lower()}"
        )


        approval_state = {}

        if APPROVED_FLAG.exists():

            try:

                approval_state = json.loads(
                    APPROVED_FLAG.read_text()
                )

                if not isinstance(
                    approval_state,
                    dict,
                ):
                    approval_state = {}

            except Exception:

                approval_state = {}


        if not approval_state.get(
            approval_key
        ):

            tx_hash = _lim_approve(
                pk,
                exchange,
            )


            if not tx_hash:

                return (
                    False,
                    "Limitless EOA: "
                    "USDC approval gagal "
                    "atau RPC tidak mengembalikan "
                    "transaction hash",
                )


            approval_state[
                approval_key
            ] = {
                "ts": time.time(),
                "tx": tx_hash,
            }


            APPROVED_FLAG.parent.mkdir(
                exist_ok=True
            )

            APPROVED_FLAG.write_text(
                json.dumps(
                    approval_state,
                    indent=2,
                )
            )


        # ----------------------------------------------------
        # ORDER CLIENT
        #
        # SDK resmi menangani EIP-712 signing.
        # ----------------------------------------------------

        order_client = OrderClient(
            http_client=http_client,
            wallet=acct,
        )


        response = (
            await order_client.create_order(
                token_id=token_id,
                maker_amount=float(usd),
                side=Side.BUY,
                order_type=OrderType.FOK,
                market_slug=market.slug,
            )
        )


        matches = (
            getattr(
                response,
                "maker_matches",
                None,
            )
            or []
        )


        order_obj = getattr(
            response,
            "order",
            None,
        )


        order_id = getattr(
            order_obj,
            "id",
            None,
        )


        status = getattr(
            order_obj,
            "status",
            None,
        )


        if not matches:

            return (
                False,
                "Limitless EOA: "
                "FOK tidak mendapatkan match"
                + (
                    f"; status={status}"
                    if status
                    else ""
                ),
            )


        return (
            True,
            "Limitless EOA BUY "
            f"${float(usd):.2f} "
            f"wallet={acct.address} "
            f"market={market.slug} "
            f"matches={len(matches)}"
            + (
                f" order_id={order_id}"
                if order_id
                else ""
            ),
        )


    except Exception as e:

        return (
            False,
            "Limitless EOA error: "
            f"{type(e).__name__}: {e}",
        )


    finally:

        if http_client is not None:

            try:
                await http_client.close()
            except Exception:
                pass


# def _exec_limitless_eoa(creds, usd, dry):
#     """Order via EOA (jalur sekarang) - butuh wallet_pk 64 hex"""
#     # Panggil fungsi asli exec_limitless yang sudah ada
#     # Tapi kita inline saja agar tidak recursive
#     pk = (creds.get("wallet_pk") or "").strip()
#     pk_hex = pk[2:] if pk.lower().startswith("0x") else pk
#     if len(pk_hex) != 64 or not set(pk_hex) <= set("0123456789abcdefABCDEF"):
#         return (False, f"Limitless: field Wallet Private Key berisi "
#                        f"{len(pk_hex)} hex (ALAMAT wallet) — butuh PRIVATE KEY "
#                        f"64 hex; minta re-ekspor dari wallet")
#     if not dry:
#         _lim_switch_eoa(creds)

# dari chatgpt
def _exec_limitless_eoa(
    creds,
    usd,
    dry=False,
    ticker=None,
):

    return _run_async(
        _lim_eoa_async(
            creds,
            usd,
            dry=dry,
            ticker=ticker,
        )
    )


def _log(entry: dict):
    EXEC_LOG.parent.mkdir(exist_ok=True)
    with EXEC_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# def _poly_market():
#     r = httpx.get("https://gamma-api.polymarket.com/markets", params={
#         "closed": "false", "limit": 10, "order": "volume24hr",
#         "ascending": "false"}, timeout=10)
#     for m in r.json():
#         ids = m.get("clobTokenIds")
#         ask = float(m.get("bestAsk") or 0)
#         if ids and ask > 0:
#             try:
#                 toks = json.loads(ids)
#             except Exception:
#                 continue
#             return {"q": m.get("question") or "?", "yes": toks[0], "ask": ask}
#     return None

def _poly_market():
    r = httpx.get("https://gamma-api.polymarket.com/markets", params={
        "closed": "false", "limit": 50, "order": "volume24hr",
        "ascending": "false"}, timeout=10)
    for m in r.json():
        ids = m.get("clobTokenIds")
        ask = float(m.get("bestAsk") or 0)
        if ids and 0.25 <= ask <= 0.75:          # posisi wajar, bukan lotre 1¢
            try:
                toks = json.loads(ids)
            except Exception:
                continue
            return {"q": m.get("question") or "?", "yes": toks[0], "ask": ask}
    return None

def exec_polymarket(creds, usd=2, dry=False, ticker=None):
    m = _poly_market()
    if not m:
        return False, "tidak ada market likuid"
    price = min(round(m["ask"] + 0.01, 2), 0.99)
    size = max(1, int(usd // price))
    if dry:
        return True, f"[DRY] BUY YES {size} x {price} :: {m['q'][:50]}"
    # ---- GUARDRAIL: order real wajib proxy (deposit wallet flow) ----
    if not dry and not creds.get("proxy_address"):                      # ← TAMBAH
        return (False, "Poly real butuh Deposit/Proxy Wallet Address — "
                       "isi di /setup (deposit wallet flow wajib)")     # ← TAMBAH
    try:
        # from py_clob_client_v2 import ClobClient
        # from py_clob_client_v2.clob_types import OrderArgs, OrderType
        # from py_clob_client_v2.order_builder.constants import BUY
        # c = ClobClient(host="https://clob.polymarket.com", chain_id=137,
        #                key=creds.get("private_key", ""))
        # try:
        #     api = c.create_or_derive_api_key()
        # except Exception:
        #     api = c.derive_api_key()
        # if api is not None and hasattr(c, "set_api_creds"):
        #     c.set_api_creds(api)                 # ← kunci: header L2 terpasang
        # order = c.create_order(OrderArgs(token_id=m["yes"], price=price,
        #                                  size=size, side=BUY))
        # resp = c.post_order(order, OrderType.FAK)

        from py_clob_client_v2 import ClobClient
        from py_clob_client_v2.clob_types import OrderArgs, OrderType
        from py_clob_client_v2.order_builder.constants import BUY
        client_args = {
            "host": "https://clob.polymarket.com",
            "chain_id": 137,
            "key": creds.get("private_key", ""),
        }
        proxy = creds.get("proxy_address")
        if proxy:
            client_args["funder"] = proxy          # ← deposit wallet flow
            client_args["signature_type"] = 2     # POLY_PROXY — workaround resmi            
        c = ClobClient(**client_args)
        try:
            api = c.create_or_derive_api_key()
        except Exception:
            api = c.derive_api_key()
        if api is not None and hasattr(c, "set_api_creds"):
            c.set_api_creds(api)
        order = c.create_order(OrderArgs(token_id=m["yes"], price=price,
                                         size=size, side=BUY))
        resp = c.post_order(order, OrderType.FAK)
        
        _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "venue": "polymarket",
              "side": "BUY-YES", "price": price, "size": size,
              "resp": str(resp)[:120]})
        return True, f"BUY YES {size} x {price} :: {m['q'][:40]}"
    except Exception as e:
        return False, f"gagal: {e}"


# def _kalshi_market(base):
#     re_ = httpx.get(base + "/trade-api/v2/events",
#                     params={"limit": 100, "status": "open"}, timeout=15)
#     evs = sorted([e for e in re_.json().get("events", [])
#                   if not (e.get("ticker") or "").startswith("KXMVE")],
#                  key=lambda e: float(e.get("volume") or 0), reverse=True)
#     for ev in evs[:10]:
#         rm = httpx.get(base + "/trade-api/v2/markets",
#                        params={"event_ticker": ev.get("ticker"),
#                                "status": "open"}, timeout=12)
#         for m in rm.json().get("markets", []):
#             ask = float(m.get("yes_ask_dollars") or 0)
#             if 0.05 < ask < 0.95:
#                 return {"t": m["ticker"], "ask": ask,
#                         "q": m.get("title") or ev.get("ticker")}
#     return None

# def _kalshi_market(base):
#     def get(params):
#         try:
#             r = httpx.get(base + "/trade-api/v2/markets",
#                           params=params, timeout=15)
#             return r.json() if r.status_code == 200 else None
#         except Exception:
#             return None

#     pages = []
#     j = get({"limit": 500, "status": "open", "order_by": "volume"})
#     if j is None:                                   # server tak kenal order_by
#         j = get({"limit": 500, "status": "open"})
#     while j and len(pages) < 6:                     # maks ±3.000 market
#         pages.append(j)
#         cur = j.get("cursor")
#         if not cur:
#             break
#         j = get({"limit": 500, "status": "open", "cursor": cur})

#     best = None
#     for pg in pages:
#         for m in pg.get("markets", []):
#             t = m.get("ticker") or ""
#             if t.startswith("KXMVE"):
#                 continue
#             ask = float(m.get("yes_ask_dollars") or 0)
#             vol = float(m.get("volume_fp") or 0)
#             if 0.05 < ask < 0.95 and (best is None or vol > best["vol"]):
#                 best = {"t": t, "ask": ask, "vol": vol,
#                         "q": m.get("title") or t}
#         if best and best["vol"] > 0:
#             break
#     return best

def _kalshi_market(base):
    best = None
    for ser in SERIES_CANDIDATES:
        try:
            r = httpx.get(base + "/trade-api/v2/markets",
                          params={"limit": 50, "status": "open",
                                  "series_ticker": ser}, timeout=12)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        for m in r.json().get("markets", []):
            t = m.get("ticker") or ""
            if t.startswith("KXMVE"):
                continue
            ask = float(m.get("yes_ask_dollars") or 0)
            vol = float(m.get("volume_fp") or 0)
            if 0.05 < ask < 0.95 and (best is None or vol > best["vol"]):
                best = {"t": t, "ask": ask, "vol": vol, "q": m.get("title") or t}
        if best and best["vol"] > 0:
            break
    return best

# def exec_kalshi(creds, usd=2, dry=False, ticker=None):
#     # m = _k_market()
#     m = _k_market(creds, ticker=ticker)     # ← ganti baris lama
#     if not m:
#         return False, "tidak ada market kalshi likuid"
#     price = min(round(m["yes"] + 0.01, 2), 0.99)
#     size = max(1, int(usd // price))
#     if dry:
#         return True, f"[DRY] kalshi BUY YES {size} x {price} :: {m['ticker']}"
#     # path = KALSHI_ROOT + "/portfolio/events/orders"
#     # body = json.dumps({
#     #     "ticker": m["ticker"],
#     #     "side": "bid",
#     #     "count": f"{size:.2f}",
#     #     "price": f"{price:.4f}",
#     #     "client_order_id": str(_uuid.uuid4()),
#     # }, separators=(",", ":"))
#     # log = []
#     # for host in (KALSHI_HOST, "https://api.elections.kalshi.com"):
#     #     for variant_name, payload_fn in [
#     #         ("A:ts+method+path", lambda t: f"{t}POST{path}"),
#     #         ("B:ts+method+path+body", lambda t: f"{t}POST{path}{body}"),
#     #         ("C:method+path+body+ts", lambda t: f"POST{path}{body}{t}"),
#     #         ("D:method+path+ts", lambda t: f"POST{path}{t}"),
#     #     ]:
#     #         ts = str(int(time.time() * 1000))
#     #         key = serialization.load_pem_private_key(creds.get("private_key_pem", "").encode(), password=None)
#     #         sig = base64.b64encode(key.sign(payload_fn(ts).encode(),
#     #             padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
#     #                         salt_length=padding.PSS.DIGEST_LENGTH),
#     #             hashes.SHA256())).decode()
#     #         hdrs = {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
#     #                 "KALSHI-ACCESS-SIGNATURE": sig,
#     #                 "KALSHI-ACCESS-TIMESTAMP": ts,
#     #                 "Content-Type": "application/json"}
#     #         with httpx.Client(timeout=15) as client:
#     #             r = client.post(host + path, headers=hdrs, content=body)
#     #         tag = f"[{host.split('://')[1]}|{variant_name}]"
#     #         log.append(f"{tag} {r.status_code}")
#     #         if r.status_code < 400:
#     #             return True, f"BUY YES {size} x {price} :: {m['ticker']}"
#     # return False, "kalshi: " + " | ".join(log)

#     path = KALSHI_ROOT + "/portfolio/events/orders"
#     body = json.dumps({
#         "ticker": m["ticker"],
#         "side": "bid",
#         "count": f"{size:.2f}",
#         "price": f"{price:.4f}",
#         "client_order_id": str(_uuid.uuid4()),
#     }, separators=(",", ":"))

#     body_hash = hashlib.sha256(body.encode()).hexdigest()
#     log = []

#     for host in (KALSHI_HOST, "https://api.elections.kalshi.com"):
#         for variant_name, payload_fn in [
#             ("A:ts+method+path", lambda t: f"{t}POST{path}"),
#             ("B:ts+method+path+body", lambda t: f"{t}POST{path}{body}"),
#             ("C:ts+method+path+hash", lambda t: f"{t}POST{path}{body_hash}"),
#             ("D:method+path+hash+ts", lambda t: f"POST{path}{body_hash}{t}"),
#         ]:
#             ts = str(int(time.time() * 1000))
#             key = serialization.load_pem_private_key(creds.get("private_key_pem", "").encode(), password=None)
#             sig = base64.b64encode(key.sign(payload_fn(ts).encode(),
#                 padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
#                             salt_length=padding.PSS.DIGEST_LENGTH),
#                 hashes.SHA256())).decode()
#             hdrs = {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
#                     "KALSHI-ACCESS-SIGNATURE": sig,
#                     "KALSHI-ACCESS-TIMESTAMP": ts,
#                     "Content-Type": "application/json"}
#             with httpx.Client(timeout=15) as client:
#                 r = client.post(host + path, headers=hdrs, content=body)
#             tag = f"[{host.split('://')[1]}|{variant_name}]"
#             log.append(f"{tag} {r.status_code}")
#             if r.status_code < 400:
#                 return True, f"BUY YES {size} x {price} :: {m['ticker']}"
#     return False, "kalshi: " + " | ".join(log)
#     return True, f"BUY YES {size} x {price} :: {m['ticker']}"

def exec_kalshi(creds, usd=2, dry=False, ticker=None):
    m = _k_market(creds, ticker=ticker)
    if not m:
        return False, "tidak ada market kalshi likuid"
    price = min(round(m["yes"] + 0.01, 2), 0.99)
    size = max(1, int(usd // price))
    if dry:
        return True, f"[DRY] kalshi BUY YES {size} x {price} :: {m['ticker']}"
    path = KALSHI_ROOT + "/portfolio/events/orders"
    body = json.dumps({
        "ticker": m["ticker"],
        "side": "bid",
        "count": f"{size:.2f}",
        "price": f"{price:.4f}",
        "client_order_id": str(_uuid.uuid4()),
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
    }, separators=(",", ":"))
    ts = str(int(time.time() * 1000))
    key = serialization.load_pem_private_key(
        creds.get("private_key_pem", "").encode(), password=None)
    sig = base64.b64encode(key.sign(f"{ts}POST{path}".encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256())).decode()
    hdrs = {"KALSHI-ACCESS-KEY": creds.get("api_key_id", ""),
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"}
    with httpx.Client(timeout=15) as client:
        r = client.post(KALSHI_HOST + path, headers=hdrs, content=body)
    if r.status_code >= 400:
        return False, f"kalshi {r.status_code}: {r.text[:200]}"
    return True, f"BUY YES {size} x {price} :: {m['ticker']}"

# def exec_limitless(creds, usd=1, dry=False):
#     return False, ("Limitless read-only: order butuh tanda tangan EIP-712 "
#                    "wallet / delegated partner (di luar scope fase ini)")


EXEC = {"polymarket": exec_polymarket, "kalshi": exec_kalshi,
        "limitless": exec_limitless}