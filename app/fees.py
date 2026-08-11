"""
Modul Perhitungan Fee 3 Venue (Kalshi, Polymarket, Limitless)
Sesuai blueprint 16-PAIRING-COMBINATIONS.pdf v1.0.0 (9 Agt 2026)
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Optional

# ==========================
# KALSHI
# ==========================
# Multiplier default; series tertentu bisa override (M=0 = gratis)
KALSHI_TAKER_BASE = Decimal("0.07")
KALSHI_MAKER_BASE = Decimal("0.0175")

# Contoh series dengan multiplier non-standar (subset dari ~80 series)
KALSHI_SERIES_MULTIPLIER = {
    "KXBTCY": (Decimal("0"), Decimal("0")),      # BTC year-end: GRATIS
    "KXETHY": (Decimal("0"), Decimal("0")),      # ETH year-end: GRATIS
    "KXFED":  (Decimal("1"), Decimal("1")),      # Fed: standar
    "KXCPI":  (Decimal("1"), Decimal("1")),      # CPI: standar
    "KXGDP":  (Decimal("1"), Decimal("1")),      # GDP: standar
    "KXBTCMAX150": (Decimal("1"), Decimal("1")), # BTC tembus 150k: STANDAR (bukan gratis!)
    # Event niche gratis:
    "KXCITRINI": (Decimal("0"), Decimal("0")),
    "KXGREENLAND": (Decimal("0"), Decimal("0")),
}

# def fee_kalshi(C: int, P: Decimal, side: str = "taker",
#                series: Optional[str] = None) -> Decimal:
#     """
#     Fee Kalshi per ORDER (bukan per kontrak). Dibulatkan ke atas (ceil) ke sen.
    
#     Args:
#         C: jumlah kontrak (integer)
#         P: harga (Decimal antara 0.01 dan 0.99)
#         side: "taker" atau "maker"
#         series: ticker series (misal "KXBTCY"); None = default (M=1)
    
#     Returns:
#         Fee dalam USD (Decimal)
#     """
#     if side not in ("taker", "maker"):
#         raise ValueError(f"side harus 'taker' atau 'maker', dapat: {side}")
    
#     # Ambil multiplier
#     if series and series in KALSHI_SERIES_MULTIPLIER:
#         M_taker, M_maker = KALSHI_SERIES_MULTIPLIER[series]
#     else:
#         M_taker, M_maker = Decimal("1"), Decimal("1")
    
#     M = M_taker if side == "taker" else M_maker
    
#     # Hitung fee dalam satuan SEN
#     fee_cents = (M * KALSHI_TAKER_BASE * C * P * (1 - P)
#                  if side == "taker"
#                  else M * KALSHI_MAKER_BASE * C * P * (1 - P))
#     fee_cents = fee_cents.to_integral_value(rounding=ROUND_CEILING)
    
#     # Konversi ke Dolar (2 desimal)
#     return fee_cents / Decimal("100")

def fee_kalshi(C: int, P: Decimal, side: str = "taker",
               series: Optional[str] = None) -> Decimal:
    """
    Fee Kalshi per ORDER (bukan per kontrak). 
    Rumus langsung menghasilkan DOLAR, lalu dibulatkan ke atas (ceil) ke sen terdekat (2 desimal).
    """
    if side not in ("taker", "maker"):
        raise ValueError(f"side harus 'taker' atau 'maker', dapat: {side}")
    
    # Ambil multiplier
    if series and series in KALSHI_SERIES_MULTIPLIER:
        M_taker, M_maker = KALSHI_SERIES_MULTIPLIER[series]
    else:
        M_taker, M_maker = Decimal("1"), Decimal("1")
    
    M = M_taker if side == "taker" else M_maker
    
    # Hitung fee langsung dalam satuan DOLAR (bukan sen)
    fee_dollars = (M * KALSHI_TAKER_BASE * C * P * (1 - P)
                   if side == "taker"
                   else M * KALSHI_MAKER_BASE * C * P * (1 - P))
    
    # Bulatkan ke atas ke sen terdekat (2 angka di belakang koma)
    return fee_dollars.quantize(Decimal("0.01"), rounding=ROUND_CEILING)

# ==========================
# POLYMARKET
# ==========================
# feeRate per kategori (sumber: docs.polymarket.com/trading/fees)
POLYMARKET_FEE_RATE = {
    "Geopolitics": Decimal("0.00"),
    "Finance":     Decimal("0.04"),
    "Politics":    Decimal("0.04"),
    "Mentions":    Decimal("0.04"),
    "Tech":        Decimal("0.04"),
    "Sports":      Decimal("0.05"),
    "Economics":   Decimal("0.05"),
    "Culture":     Decimal("0.05"),
    "Weather":     Decimal("0.05"),
    "Other":       Decimal("0.05"),
    "Crypto":      Decimal("0.07"),
}

def fee_polymarket(C: int, P: Decimal, kategori: str,
                   fee_rate_override: Optional[Decimal] = None) -> Decimal:
    """
    Fee Polymarket per ORDER. Dibulatkan ke 5 desimal (0.00001 USDC).
    
    Args:
        C: jumlah kontrak
        P: harga (Decimal antara 0.01 dan 0.99)
        kategori: salah satu dari POLYMARKET_FEE_RATE.keys()
        fee_rate_override: bila rate kategori sudah diketahui dari API
    
    Returns:
        Fee dalam USDC (Decimal)
    """
    if fee_rate_override is not None:
        rate = fee_rate_override
    elif kategori in POLYMARKET_FEE_RATE:
        rate = POLYMARKET_FEE_RATE[kategori]
    else:
        raise ValueError(f"Kategori '{kategori}' tidak dikenal")
    
    fee = rate * C * P * (1 - P)
    # Bulatkan ke 5 desimal (USDC precision)
    return fee.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)

# Estimasi gas Polygon (USDC) — per order, bukan per kontrak
GAS_POLYGON_USDC = Decimal("0.01")

# ==========================
# LIMITLESS (Tabel Lookup)
# ==========================
# BUY fee dalam outcome token (persentase)
LIMITLESS_BUY_FEE = [
    (Decimal("0.50"),  Decimal("0.0300")),  # 3.00%
    (Decimal("0.55"),  Decimal("0.0252")),  # 2.52%
    (Decimal("0.60"),  Decimal("0.0213")),  # 2.13%
    (Decimal("0.65"),  Decimal("0.0180")),  # 1.80%
    (Decimal("0.70"),  Decimal("0.0151")),  # 1.51%
    (Decimal("0.75"),  Decimal("0.0126")),  # 1.26%
    (Decimal("0.80"),  Decimal("0.0105")),  # 1.05%
    (Decimal("0.85"),  Decimal("0.0085")),  # 0.85%
    (Decimal("0.90"),  Decimal("0.0068")),  # 0.68%
    (Decimal("0.95"),  Decimal("0.0053")),  # 0.53%
    (Decimal("0.99"),  Decimal("0.0042")),  # 0.42%
    (Decimal("0.999"), Decimal("0.0040")),  # 0.40%
]

# SELL fee dalam USDC (persentase)
LIMITLESS_SELL_FEE = [
    (Decimal("0.01"),  Decimal("0.0042")),  # 0.42%
    (Decimal("0.05"),  Decimal("0.0060")),  # 0.60%
    (Decimal("0.10"),  Decimal("0.0078")),  # 0.78%
    (Decimal("0.20"),  Decimal("0.0111")),  # 1.11%
    (Decimal("0.30"),  Decimal("0.0132")),  # 1.32%
    (Decimal("0.40"),  Decimal("0.0144")),  # 1.44%
    (Decimal("0.50"),  Decimal("0.0150")),  # 1.50% PUNCAK
    (Decimal("0.60"),  Decimal("0.0144")),  # 1.44%
    (Decimal("0.70"),  Decimal("0.0132")),  # 1.32%
    (Decimal("0.80"),  Decimal("0.0111")),  # 1.11%
    (Decimal("0.90"),  Decimal("0.0078")),  # 0.78%
    (Decimal("0.95"),  Decimal("0.0060")),  # 0.60%
    (Decimal("0.99"),  Decimal("0.0045")),  # 0.45%
    (Decimal("0.999"), Decimal("0.0042")),  # 0.42%
]

LIMITLESS_AMM_FEE = Decimal("0.0040")  # 0.40% flat


def _interpolate(table, P: Decimal) -> Decimal:
    """
    Interpolasi linear antar titik tabel.
    PERINGATAN: Dokumentasi Limitless TIDAK menyatakan metode interpolasi resmi.
    Ini asumsi sementara; wajib diverifikasi vs API Limitless saat runtime.
    """
    if P <= table[0][0]:
        return table[0][1]
    if P >= table[-1][0]:
        return table[-1][1]
    
    for i in range(len(table) - 1):
        p_low, f_low = table[i]
        p_high, f_high = table[i + 1]
        if p_low <= P <= p_high:
            ratio = (P - p_low) / (p_high - p_low)
            return f_low + ratio * (f_high - f_low)
    
    return table[-1][1]  # fallback


def fee_limitless(C: int, P: Decimal, side: str,
                  market_type: str = "clob") -> Decimal:
    """
    Fee Limitless per ORDER. 
    
    Args:
        C: jumlah kontrak
        P: harga
        side: "buy" atau "sell"
        market_type: "clob" (order book) atau "amm" (flat 0.40%)
    
    Returns:
        Fee dalam USDC (Decimal)
    """
    if market_type == "amm":
        fee_rate = LIMITLESS_AMM_FEE
    elif market_type == "clob":
        if side == "buy":
            fee_rate = _interpolate(LIMITLESS_BUY_FEE, P)
        elif side == "sell":
            fee_rate = _interpolate(LIMITLESS_SELL_FEE, P)
        else:
            raise ValueError(f"side harus 'buy' atau 'sell', dapat: {side}")
    else:
        raise ValueError(f"market_type harus 'clob' atau 'amm', dapat: {market_type}")
    
    fee = fee_rate * C * P
    return fee.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)


# ==========================
# KALKULATOR PROFIT BERSIH (Π)
# ==========================
def profit_bersih_pair(
    C: int,
    P1: Decimal,
    P2: Decimal,
    fee1: Decimal,
    fee2: Decimal,
    gas: Decimal = GAS_POLYGON_USDC,
    buffer_slippage: Decimal = Decimal("0.005"),
) -> Decimal:
    """
    Π(C) = C × $1.00 − (keluar_kaki_1 + keluar_kaki_2)
    kaki_i = C × P_i + fee_i (+ gas jika Polymarket)
    """
    keluar1 = C * P1 + fee1
    keluar2 = C * P2 + fee2 + gas
    return C * Decimal("1.00") - (keluar1 + keluar2)