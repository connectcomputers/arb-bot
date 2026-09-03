# /app/execution/limitless_executor.py
"""
Limitless Executor.

Mendukung dua mode:

1. eoa
   - Wallet pribadi
   - Private key 0x + 64 hex
   - Limitless standard API key
   - EIP-712 signing

2. smartWallet
   - Limitless Managed / Server Wallet
   - Partner HMAC token_id + secret
   - Delegated child profile ID
   - delegated_orders.create_order(..., on_behalf_of=profile_id)

PENTING:
- dry=True TIDAK melakukan order.
- dry=True TIDAK melakukan approval.
- dry=True TIDAK mengirim transaksi blockchain.
- Tidak ada hard-coded wallet address.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any, Optional

from eth_account import Account

from app.execution.base import (
    Executor,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderSide,
    OrderOutcome,
)

try:
    from limitless_sdk.api import HttpClient, APIError
    from limitless_sdk.orders import OrderClient
    from limitless_sdk.markets import MarketFetcher
    from limitless_sdk.types import Side as LSide
    from limitless_sdk.types import OrderType as LOrderType
    from limitless_sdk import Client as LimitlessClient
    from limitless_sdk import HMACCredentials

    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False


LIMITLESS_BASE_URL = "https://api.limitless.exchange"

from decimal import Decimal as _D

USDC_BASE_ADDR = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

def _usdc_balance_onchain(addr: str) -> _D:
    import httpx as _hx
    data = "0x70a08231" + addr[2:].lower().rjust(64, "0")
    r = _hx.post("https://mainnet.base.org",
                 json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                       "params": [{"to": USDC_BASE_ADDR, "data": data}, "latest"]},
                 timeout=10)
    res = r.json().get("result") or "0x0"
    return _D(int(res, 16)) / _D(1_000_000)

def _err_text(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status is not None:
        return f"Limitless API {status}: {exc}"
    return f"{type(exc).__name__}: {exc}"


def _to_side(side: OrderSide) -> Any:
    return LSide.BUY if side == OrderSide.BUY else LSide.SELL


def _to_order_type(order_type) -> Any:
    value = getattr(order_type, "value", str(order_type))
    value = value.upper()

    if value == "GTC":
        return LOrderType.GTC

    if value == "FAK":
        return LOrderType.FAK

    if value == "FOK":
        return LOrderType.FOK

    raise ValueError(f"Order type Limitless tidak didukung: {value}")


def _run(coro):
    """
    Jalankan coroutine dari engine synchronous.

    Engine lama Anda menggunakan fungsi synchronous:
        exec_limitless(...)

    sehingga kita menyediakan bridge yang aman.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Jika dipanggil dari thread yang sudah memiliki event loop,
    # jalankan coroutine di thread event-loop terpisah.
    import threading

    result = []
    error = []

    def runner():
        try:
            result.append(asyncio.run(coro))
        except Exception as exc:
            error.append(exc)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join()

    if error:
        raise error[0]

    return result[0]

# dari chatgpt
def exec_limitless(
    creds,
    usd=2,
    dry=False,
    ticker=None,
):
    """
    Compatibility wrapper.

    Engine lama tetap memanggil:
        exec_limitless(creds, usd=..., dry=...)

    Tetapi implementation Limitless sekarang berada
    di app.execution.limitless_executor.
    """

    from app.execution.limitless_executor import (
        LimitlessExecutor,
        _run,
    )

    mode = (
        creds.get("wallet_mode")
        or "eoa"
    )

    # ------------------------------------------------------------
    # Untuk compatibility dengan micro test lama,
    # kita lakukan market discovery terlebih dahulu.
    # ------------------------------------------------------------

    import httpx

    try:

        if ticker:
            slug = ticker

        else:
            r = httpx.get(
                "https://api.limitless.exchange/markets/active",
                params={"limit": 25},
                timeout=15,
            )

            r.raise_for_status()

            data = r.json().get(
                "data",
                [],
            )

            market = next(
                (
                    x
                    for x in data
                    if x.get("prices")
                    and len(x["prices"]) == 2
                ),
                None,
            )

            if not market:
                return (
                    False,
                    "Limitless: tidak ada market aktif.",
                )

            slug = market["slug"]

        # --------------------------------------------------------
        # Kita perlu harga untuk FOK.
        #
        # Untuk test micro BUY:
        # maker_amount = usd
        #
        # Jadi size dihitung dari harga ask yang tersedia.
        # --------------------------------------------------------

        r = httpx.get(
            f"https://api.limitless.exchange/markets/{slug}",
            timeout=15,
        )

        r.raise_for_status()

        d = r.json().get(
            "data",
            {},
        )

        prices = d.get("prices") or []

        if len(prices) < 1:
            return (
                False,
                f"Limitless: market {slug} "
                "tidak memiliki price.",
            )

        price = float(
            prices[0]
        )

        if price <= 0 or price >= 1:
            return (
                False,
                f"Limitless: harga tidak valid: {price}",
            )

        # --------------------------------------------------------
        # OrderRequest
        # --------------------------------------------------------

        from decimal import Decimal
        from app.execution.base import (
            OrderRequest,
            OrderSide,
            OrderOutcome,
            OrderType,
        )

        # FOK BUY YES.
        #
        # size harus cukup agar:
        # size * price ~= usd
        size = max(
            1,
            int(
                Decimal(str(usd))
                / Decimal(str(price))
            ),
        )

        request = OrderRequest(
            venue="limitless",
            market_id=slug,
            side=OrderSide.BUY,
            outcome=OrderOutcome.YES,
            price=Decimal(str(price)),
            size=size,
            order_type=OrderType.FOK,
        )

        executor = LimitlessExecutor(
            live=not dry,
            creds=creds,
        )

        result = _run(
            executor.submit_order(
                request
            )
        )

        if result.is_success:

            return (
                True,
                (
                    f"Limitless {mode} "
                    f"BUY YES "
                    f"${usd:.4f} "
                    f"order={result.order_id}"
                ),
            )

        return (
            False,
            (
                result.error_message
                or (
                    f"Limitless {mode}: "
                    f"status={result.status.value} "
                    f"order={result.order_id}"
                )
            ),
        )

    except Exception as exc:

        return (
            False,
            f"Limitless: {type(exc).__name__}: {exc}",
        )
    
class LimitlessExecutor(Executor):

    def __init__(
        self,
        live: bool = False,
        creds: Optional[dict] = None,
        api_key: str = "",
    ):
        super().__init__(live=live)

        self.venue_name = "limitless"
        self.creds = dict(creds or {})

        if api_key and not self.creds.get("eoa_api_key"):
            self.creds["eoa_api_key"] = api_key

        self._simulated_fills = {}

    # ------------------------------------------------------------------
    # PUBLIC
    # ------------------------------------------------------------------

    async def submit_order(self, request: OrderRequest) -> OrderResult:

        if request.venue.lower() != "limitless":
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                error_message=(
                    f"Venue mismatch: expected limitless, "
                    f"got {request.venue}"
                ),
                timestamp=int(time.time()),
            )

        if not self.live:
            return await self._simulate_fill(request)

        try:
            mode = (
                self.creds.get("wallet_mode")
                or "eoa"
            ).strip()

            if mode == "eoa":
                return await self._submit_eoa(request)

            if mode == "smartWallet":
                return await self._submit_smart_wallet(request)

            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                error_message=(
                    f"Limitless wallet_mode tidak dikenal: {mode}. "
                    f"Gunakan 'eoa' atau 'smartWallet'."
                ),
                timestamp=int(time.time()),
            )

        except Exception as exc:
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                error_message=_err_text(exc),
                timestamp=int(time.time()),
            )

    # ------------------------------------------------------------------
    # SIMULATION
    # ------------------------------------------------------------------

    async def _simulate_fill(
        self,
        request: OrderRequest,
    ) -> OrderResult:

        order_id = (
            f"LMT-SIM-{time.time_ns()}"
        )

        filled_price = (
            request.worst_price
            if request.worst_price is not None
            else request.price
        )

        result = OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            filled_size=request.size,
            filled_price=filled_price,
            timestamp=int(time.time()),
            raw_response={
                "simulated": True,
                "wallet_mode": self.creds.get(
                    "wallet_mode",
                    "eoa",
                ),
            },
        )

        self._simulated_fills[order_id] = result

        return result

    # ------------------------------------------------------------------
    # EOA
    # ------------------------------------------------------------------

    def _validate_eoa(self) -> str:

        pk = str(
            self.creds.get("wallet_pk") or ""
        ).strip()

        pk_hex = (
            pk[2:]
            if pk.lower().startswith("0x")
            else pk
        )

        if len(pk_hex) != 64:
            raise ValueError(
                "Limitless EOA: wallet_pk harus "
                "PRIVATE KEY 64 hex "
                "(0x + 64 hex). "
                f"Saat ini {len(pk_hex)} hex."
            )

        if not all(
            ch in "0123456789abcdefABCDEF"
            for ch in pk_hex
        ):
            raise ValueError(
                "Limitless EOA: wallet_pk mengandung "
                "karakter non-hex."
            )

        # Pastikan benar-benar private key Ethereum.
        account = Account.from_key(pk)

        return account.address

    def _eoa_api_key(self) -> str:

        key = str(
            self.creds.get("eoa_api_key")
            or ""
        ).strip()

        if not key:
            raise ValueError(
                "Limitless EOA: eoa_api_key kosong. "
                "EOA menggunakan standard Limitless API key; "
                "jangan memakai HMAC token ID sebagai penggantinya."
            )

        return key

    async def _submit_eoa(
        self,
        request: OrderRequest,
    ) -> OrderResult:

        address = self._validate_eoa()
        hmac_credentials=HMACCredentials(
            token_id=self.creds.get("api_key"),
            secret=self.creds.get("api_secret"),
        ),
        private_key = str(
            self.creds.get("wallet_pk") or ""
        ).strip()

        http_client = HttpClient(
            base_url=LIMITLESS_BASE_URL,
            hmac_credentials=HMACCredentials(
                token_id=self.creds.get("api_key"),
                secret=self.creds.get("api_secret"),
            ),
        )

        try:
            market_fetcher = MarketFetcher(
                http_client
            )

            market = await market_fetcher.get_market(
                request.market_id
            )

            if not market.tokens:
                raise ValueError(
                    f"Market {request.market_id} "
                    "tidak mempunyai token."
                )

            if request.outcome == OrderOutcome.YES:
                token_id = str(
                    market.tokens.yes
                )
            else:
                token_id = str(
                    market.tokens.no
                )

            if not token_id:
                raise ValueError(
                    "Token ID Limitless kosong."
                )

            order_client = OrderClient(
                http_client=http_client,
                wallet=Account.from_key(
                    private_key
                ),
            )

            order_type = _to_order_type(
                request.order_type
            )

            side = _to_side(request.side)

            kwargs = {
                "token_id": token_id,
                "side": side,
                "order_type": order_type,
                "market_slug": market.slug,
            }

            if order_type == LOrderType.FOK:

                # Untuk BUY FOK:
                # maker_amount = total USDC yang dibelanjakan.
                if request.side == OrderSide.BUY:
                    maker_amount = float(
                        Decimal(request.size)
                        * request.price
                    )
                else:
                    # SELL FOK:
                    # maker_amount = jumlah shares.
                    maker_amount = float(
                        Decimal(request.size)
                    )

                if maker_amount <= 0:
                    raise ValueError(
                        "maker_amount harus > 0."
                    )

                kwargs["maker_amount"] = (
                    maker_amount
                )

            else:
                kwargs["price"] = float(
                    request.price
                )
                kwargs["size"] = float(
                    request.size
                )

                if (
                    order_type == LOrderType.GTC
                    and request.order_type.value == "GTC"
                ):
                    # Tidak memaksa post_only.
                    # Arbitrage engine biasanya lebih cocok
                    # dengan order yang dapat langsung dieksekusi.
                    pass

            response = await order_client.create_order(
                **kwargs
            )

            order_id = str(
                response.order.id
            )

            matches = getattr(
                response,
                "maker_matches",
                None,
            ) or []

            filled_size = 0

            for match in matches:
                try:
                    filled_size += int(
                        float(
                            getattr(
                                match,
                                "matched_size",
                                0,
                            )
                        )
                    )
                except Exception:
                    pass

            if matches:
                status = OrderStatus.FILLED
            else:
                if order_type == LOrderType.FOK:
                    status = OrderStatus.CANCELLED
                else:
                    status = OrderStatus.PENDING

            return OrderResult(
                order_id=order_id,
                status=status,
                filled_size=(
                    filled_size
                    if filled_size > 0
                    else (
                        request.size
                        if status == OrderStatus.FILLED
                        else 0
                    )
                ),
                filled_price=request.price,
                timestamp=int(time.time()),
                raw_response={
                    "wallet_mode": "eoa",
                    "wallet": address,
                    "market": market.slug,
                    "token_id": token_id,
                    "response": str(response),
                },
            )

        except Exception as exc:
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                timestamp=int(time.time()),
                error_message=(
                    f"Limitless EOA: {_err_text(exc)}"
                ),
            )

        finally:
            await http_client.close()

    # ------------------------------------------------------------------
    # MANAGED / SERVER WALLET
    # ------------------------------------------------------------------

    def _validate_smart_wallet(self):

        token_id = str(
            self.creds.get("api_key") or ""
        ).strip()

        secret = str(
            self.creds.get("api_secret") or ""
        ).strip()

        # profile_id = self.creds.get(
        #     "delegated_profile_id"
        # )

        profile_id = (
            self.creds.get("delegated_profile_id")
            or self.creds.get("smart_wallet_profile_id")
        )

        if not token_id:
            raise ValueError(
                "Limitless Managed Wallet: "
                "HMAC token ID/api_key kosong."
            )

        if not secret:
            raise ValueError(
                "Limitless Managed Wallet: "
                "HMAC secret/api_secret kosong."
            )

        if profile_id in (
            None,
            "",
            0,
            "0",
        ):
            raise ValueError(
                "Limitless Managed Wallet: "
                "delegated_profile_id kosong."
            )

        try:
            profile_id = int(profile_id)
        except Exception:
            raise ValueError(
                "delegated_profile_id harus berupa integer."
            )

        if profile_id <= 0:
            raise ValueError(
                "delegated_profile_id harus > 0."
            )

        return token_id, secret, profile_id

    async def _submit_smart_wallet(
        self,
        request: OrderRequest,
    ) -> OrderResult:

        token_id_hmac, secret, profile_id = (
            self._validate_smart_wallet()
        )

        client = LimitlessClient(
            base_url=LIMITLESS_BASE_URL,
            hmac_credentials=HMACCredentials(
                token_id=token_id_hmac,
                secret=secret,
            ),
        )

        try:

            market = await client.markets.get_market(
                request.market_id
            )

            if not market.tokens:
                raise ValueError(
                    f"Market {request.market_id} "
                    "tidak mempunyai token."
                )

            if request.outcome == OrderOutcome.YES:
                token_id = str(
                    market.tokens.yes
                )
            else:
                token_id = str(
                    market.tokens.no
                )

            if not token_id:
                raise ValueError(
                    "Token ID Limitless kosong."
                )

            kwargs = {
                "token_id": token_id,
                "side": _to_side(request.side),
                "order_type": _to_order_type(
                    request.order_type
                ),
                "market_slug": market.slug,
                "on_behalf_of": profile_id,
            }

            order_type = kwargs["order_type"]

            if order_type == LOrderType.FOK:

                if request.side == OrderSide.BUY:
                    kwargs["maker_amount"] = float(
                        Decimal(request.size)
                        * request.price
                    )
                else:
                    kwargs["maker_amount"] = float(
                        Decimal(request.size)
                    )

            else:
                kwargs["price"] = float(
                    request.price
                )
                kwargs["size"] = float(
                    request.size
                )

            response = (
                await client.delegated_orders.create_order(
                    **kwargs
                )
            )

            order_id = str(
                response.order.id
            )

            matches = getattr(
                response,
                "maker_matches",
                None,
            ) or []

            filled_size = 0

            for match in matches:
                try:
                    filled_size += int(
                        float(
                            getattr(
                                match,
                                "matched_size",
                                0,
                            )
                        )
                    )
                except Exception:
                    pass

            if matches:
                status = OrderStatus.FILLED
            else:
                if order_type == LOrderType.FOK:
                    status = OrderStatus.CANCELLED
                else:
                    status = OrderStatus.PENDING

            return OrderResult(
                order_id=order_id,
                status=status,
                filled_size=(
                    filled_size
                    if filled_size > 0
                    else (
                        request.size
                        if status == OrderStatus.FILLED
                        else 0
                    )
                ),
                filled_price=request.price,
                timestamp=int(time.time()),
                raw_response={
                    "wallet_mode": "smartWallet",
                    "delegated_profile_id": profile_id,
                    "market": market.slug,
                    "token_id": token_id,
                    "response": str(response),
                },
            )

        except Exception as exc:

            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                timestamp=int(time.time()),
                error_message=(
                    "Limitless Managed Wallet: "
                    f"{_err_text(exc)}"
                ),
            )

        finally:
            await client.close()

    # ------------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------------

    async def cancel_order(
        self,
        order_id: str,
    ) -> bool:

        if not self.live:
            return self._simulated_fills.pop(
                order_id,
                None,
            ) is not None

        mode = (
            self.creds.get("wallet_mode")
            or "eoa"
        )

        try:

            if mode == "smartWallet":

                token_id, secret, profile_id = (
                    self._validate_smart_wallet()
                )

                client = LimitlessClient(
                    base_url=LIMITLESS_BASE_URL,
                    hmac_credentials=HMACCredentials(
                        token_id=token_id,
                        secret=secret,
                    ),
                )

                try:
                    await client.delegated_orders.cancel_on_behalf_of(
                        order_id,
                        profile_id,
                    )
                    return True
                finally:
                    await client.close()

            # EOA
            hmac_credentials=HMACCredentials(
                token_id=self.creds.get("api_key"),
                secret=self.creds.get("api_secret"),
            ),
            http_client = HttpClient(
                base_url=LIMITLESS_BASE_URL,
                hmac_credentials=HMACCredentials(
                    token_id=self.creds.get("api_key"),
                    secret=self.creds.get("api_secret"),
                ),
            )

            try:
                order_client = OrderClient(
                    http_client=http_client,
                    wallet=Account.from_key(
                        self.creds["wallet_pk"]
                    ),
                )

                await order_client.cancel(
                    order_id
                )

                return True

            finally:
                await http_client.close()

        except Exception:
            return False

    # ------------------------------------------------------------------
    # BALANCE
    # ------------------------------------------------------------------

    async def get_balance(self) -> dict:

        if not self.live:
            return {
                "venue": "limitless",
                "available": Decimal("10000"),
                "simulated": True,
            }

        mode = (
            self.creds.get("wallet_mode")
            or "eoa"
        )

        try:

            if mode == "smartWallet":

                token_id, secret, profile_id = (
                    self._validate_smart_wallet()
                )

                client = LimitlessClient(
                    base_url=LIMITLESS_BASE_URL,
                    hmac_credentials=HMACCredentials(
                        token_id=token_id,
                        secret=secret,
                    ),
                )

                try:
                    profile = (
                        await client.portfolio.get_current_profile()
                    )

                    return {
                        "venue": "limitless",
                        "available": Decimal(
                            str(
                                profile.get(
                                    "balance",
                                    0,
                                )
                            )
                        ),
                        "wallet_mode": "smartWallet",
                        "profile_id": profile_id,
                    }

                finally:
                    await client.close()

            hmac_credentials=HMACCredentials(

                token_id=self.creds.get("api_key"),

                secret=self.creds.get("api_secret"),

            ),
            http_client = HttpClient(
                base_url=LIMITLESS_BASE_URL,
                hmac_credentials=HMACCredentials(
                    token_id=self.creds.get("api_key"),
                    secret=self.creds.get("api_secret"),
                ),
            )

            try:

                profile = (
                    await MarketFetcher(
                        http_client
                    )
                )

                # Jangan mengarang balance dari market data.
                # Balance aktual harus diambil dari portfolio endpoint.
                from limitless_sdk import Client

                # client = Client(
                #     base_url=LIMITLESS_BASE_URL,
                #     api_key=api_key,
                # )

                token_id = self.creds.get("api_key")
                secret = self.creds.get("api_secret")
                client = Client(
                    base_url=LIMITLESS_BASE_URL,
                    hmac_credentials=HMACCredentials(
                        token_id=token_id,
                        secret=secret,
                    ),
                )

                try:
                    current = (
                        await client.portfolio.get_current_profile()
                    )

                    return {
                        "venue": "limitless",
                        "available": Decimal(
                            str(
                                current.get(
                                    "balance",
                                    0,
                                )
                            )
                        ),
                        "wallet_mode": "eoa",
                        "wallet": self._validate_eoa(),
                    }

                finally:
                    await client.close()

            finally:
                await http_client.close()

        except Exception as exc:

            return {
                "venue": "limitless",
                "available": Decimal("0"),
                "error": _err_text(exc),
                "wallet_mode": mode,
            }

# ==================================================================================
# """
# Limitless Executor — Mode Simulasi + interface API bearer.

# Mode live nanti:
# - Auth via API Key (header Authorization: Bearer ...)
# - POST ke https://api.limitless.com/v1/orders
# """
# import os
# import time
# import uuid
# from decimal import Decimal

# from app.execution.base import (
#     Executor, OrderRequest, OrderResult, OrderStatus, OrderSide, OrderOutcome
# )


# class LimitlessExecutor(Executor):
#     def __init__(self, live: bool = False, api_key: str = ""):
#         super().__init__(live=live)
#         self.venue_name = "limitless"
#         self.api_key = api_key or os.getenv("LIMITLESS_API_KEY", "")
#         self._simulated_fills = {}

#     async def submit_order(self, request: OrderRequest) -> OrderResult:
#         if request.venue != "limitless":
#             return OrderResult(
#                 order_id="", status=OrderStatus.REJECTED,
#                 error_message=f"Venue mismatch: expected limitless, got {request.venue}",
#                 timestamp=int(time.time()),
#             )

#         if not self.live:
#             return await self._simulate_fill(request)

#         return await self._submit_live(request)

#     async def _simulate_fill(self, request: OrderRequest) -> OrderResult:
#         order_id = f"LMT-SIM-{uuid.uuid4().hex[:8].upper()}"
#         filled_price = request.worst_price if request.worst_price else request.price

#         result = OrderResult(
#             order_id=order_id,
#             status=OrderStatus.FILLED,
#             filled_size=request.size,
#             filled_price=filled_price,
#             timestamp=int(time.time()),
#             raw_response={"simulated": True},
#         )
#         self._simulated_fills[order_id] = result
#         return result

#     async def _submit_live(self, request: OrderRequest) -> OrderResult:
#         if not self.api_key:
#             return OrderResult(
#                 order_id="", status=OrderStatus.REJECTED,
#                 error_message="LIMITLESS_API_KEY kosong",
#                 timestamp=int(time.time()),
#             )
#         # TODO Tahap 12: implement Bearer auth + POST
#         return OrderResult(
#             order_id="", status=OrderStatus.REJECTED,
#             error_message="Live mode belum diimplementasikan (Tahap 12)",
#             timestamp=int(time.time()),
#         )

#     async def cancel_order(self, order_id: str) -> bool:
#         if not self.live:
#             return order_id in self._simulated_fills
#         return False

#     async def get_balance(self) -> dict:
#         if not self.live:
#             return {"venue": "limitless", "available": Decimal("10000.00"),
#                     "simulated": True}
#         return {"venue": "limitless", "available": Decimal("0")}