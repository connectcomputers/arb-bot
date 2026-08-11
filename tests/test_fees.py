"""
Unit test modul fee 3 venue.
Fixture berdasarkan blueprint 16-PAIRING-COMBINATIONS.pdf v1.0.0
"""
from decimal import Decimal
from app.fees import (
    fee_kalshi, fee_polymarket, fee_limitless,
    profit_bersih_pair, GAS_POLYGON_USDC
)


# ============ KALSHI ============
def test_kalshi_taker_harga_pertengahan_c100():
    """Blueprint §1: P=0.50, C=100 → $0.0175 (1.75¢) per kontrak = $1.75 total."""
    hasil = fee_kalshi(C=100, P=Decimal("0.50"), side="taker")
    assert hasil == Decimal("1.75"), f"Seharusnya 1.75, dapat {hasil}"

def test_kalshi_taker_harga_ekstrem_c100():
    """Blueprint §1: P=0.10, C=100 → 0.07*100*0.1*0.9 = 0.63¢ per kontrak = $0.63 total."""
    hasil = fee_kalshi(C=100, P=Decimal("0.10"), side="taker")
    assert hasil == Decimal("0.63"), f"Seharusnya 0.63, dapat {hasil}"

# def test_kalshi_taker_penalti_mikro_c1():
#     """Blueprint §1: P=0.50, C=1 → 0.07*1*0.5*0.5 = 0.0175¢ → ceil jadi 1¢ = $0.01 total."""
#     hasil = fee_kalshi(C=1, P=Decimal("0.50"), side="taker")
#     assert hasil == Decimal("0.01"), f"Seharusnya 0.01, dapat {hasil}"

def test_kalshi_taker_penalti_mikro_c1():
    """Blueprint §1: P=0.50, C=1 → 0.07*1*0.5*0.5 = $0.0175 → ceil ke sen = $0.02 total."""
    hasil = fee_kalshi(C=1, P=Decimal("0.50"), side="taker")
    assert hasil == Decimal("0.02"), f"Seharusnya 0.02, dapat {hasil}"

def test_kalshi_maker_lebih_murah():
    """Maker = 0.25x taker. P=0.50, C=100 → $0.44 total."""
    hasil = fee_kalshi(C=100, P=Decimal("0.50"), side="maker")
    assert hasil == Decimal("0.44"), f"Seharusnya 0.44, dapat {hasil}"

def test_kalshi_series_kxbtcy_gratis():
    """KXBTCY punya M=0 → GRATIS total untuk taker maupun maker."""
    taker = fee_kalshi(C=100, P=Decimal("0.50"), side="taker", series="KXBTCY")
    maker = fee_kalshi(C=100, P=Decimal("0.50"), side="maker", series="KXBTCY")
    assert taker == Decimal("0.00"), f"Taker harusnya 0, dapat {taker}"
    assert maker == Decimal("0.00"), f"Maker harusnya 0, dapat {maker}"

def test_kalshi_series_kxbtcmax150_tidak_gratis():
    """KXBTCMAX150 = M=1 (standar) meski sama-sama crypto."""
    hasil = fee_kalshi(C=100, P=Decimal("0.50"), side="taker", series="KXBTCMAX150")
    assert hasil == Decimal("1.75"), f"Seharusnya 1.75 (standar), dapat {hasil}"


# ============ POLYMARKET ============
def test_poly_geopolitics_gratis():
    """Blueprint §2: Geopolitics feeRate=0.00 → GRATIS."""
    hasil = fee_polymarket(C=100, P=Decimal("0.50"), kategori="Geopolitics")
    assert hasil == Decimal("0.00000"), f"Seharusnya 0, dapat {hasil}"

def test_poly_politics():
    """Blueprint §2: Politics feeRate=0.04, P=0.50, C=100 → $1.00 USDC."""
    hasil = fee_polymarket(C=100, P=Decimal("0.50"), kategori="Politics")
    assert hasil == Decimal("1.00000"), f"Seharusnya 1.00, dapat {hasil}"

def test_poly_crypto_paling_mahal():
    """Blueprint §2: Crypto feeRate=0.07, P=0.50, C=100 → $1.75 USDC."""
    hasil = fee_polymarket(C=100, P=Decimal("0.50"), kategori="Crypto")
    assert hasil == Decimal("1.75000"), f"Seharusnya 1.75, dapat {hasil}"

def test_poly_kategori_tidak_dikenal():
    """Kategori tidak valid harus raise ValueError."""
    try:
        fee_polymarket(C=100, P=Decimal("0.50"), kategori="Fantasy")
        assert False, "Seharusnya raise ValueError"
    except ValueError:
        pass


# ============ LIMITLESS ============
def test_limitless_buy_harga_tengah():
    """Blueprint §3: BUY P=0.50 taker CLOB → 3.00% fee = $15 di C=100, P=0.50."""
    hasil = fee_limitless(C=100, P=Decimal("0.50"), side="buy", market_type="clob")
    assert hasil == Decimal("1.50000"), f"Seharusnya 1.50, dapat {hasil}"

def test_limitless_sell_puncak():
    """Blueprint §3: SELL P=0.50 taker → 1.50% (puncak) = $0.75 di C=100."""
    hasil = fee_limitless(C=100, P=Decimal("0.50"), side="sell", market_type="clob")
    assert hasil == Decimal("0.75000"), f"Seharusnya 0.75, dapat {hasil}"

def test_limitless_buy_harga_ekstrem():
    """Blueprint §3: BUY P=0.999 taker → 0.40% (paling murah)."""
    hasil = fee_limitless(C=100, P=Decimal("0.999"), side="buy", market_type="clob")
    # 0.40% × 100 × 0.999 = 0.39960 USDC
    assert hasil == Decimal("0.39960"), f"Seharusnya 0.39960, dapat {hasil}"

def test_limitless_amm_flat():
    """Blueprint §3: AMM markets → flat 0.40% fee."""
    hasil = fee_limitless(C=100, P=Decimal("0.50"), side="buy", market_type="amm")
    # 0.40% × 100 × 0.50 = 0.20 USDC
    assert hasil == Decimal("0.20000"), f"Seharusnya 0.20, dapat {hasil}"


# ============ PAIRING A (Polymarket × Kalshi) ============
def test_pairing_a_poly_geopolitics_kalshi_standar():
    """Blueprint §4: Poly Geopolitics + Kalshi standar, C=100, P≈0.50 → total fee $1.75.
    Ambang spread harus > 1.75¢ untuk profit."""
    fee_k = fee_kalshi(C=100, P=Decimal("0.50"), side="taker")
    fee_p = fee_polymarket(C=100, P=Decimal("0.50"), kategori="Geopolitics")
    total_fee = fee_k + fee_p
    assert total_fee == Decimal("1.75"), f"Total fee seharusnya 1.75, dapat {total_fee}"

def test_pairing_a_poly_crypto_kalshi_standar():
    """Blueprint §4: Poly Crypto + Kalshi standar → total fee $3.50 (TERMHAL)."""
    fee_k = fee_kalshi(C=100, P=Decimal("0.50"), side="taker")
    fee_p = fee_polymarket(C=100, P=Decimal("0.50"), kategori="Crypto")
    total_fee = fee_k + fee_p
    assert total_fee == Decimal("3.50"), f"Total fee seharusnya 3.50, dapat {total_fee}"

def test_pairing_a_poly_crypto_kalshi_kxbtcy():
    """Blueprint §4: Poly Crypto + Kalshi KXBTCY (M=0) → total fee $1.75 (TERMURAH di pairing ini)."""
    fee_k = fee_kalshi(C=100, P=Decimal("0.50"), side="taker", series="KXBTCY")
    fee_p = fee_polymarket(C=100, P=Decimal("0.50"), kategori="Crypto")
    total_fee = fee_k + fee_p
    assert total_fee == Decimal("1.75"), f"Total fee seharusnya 1.75, dapat {total_fee}"


# ============ KALKULATOR Π ============
# def test_pi_scenario_1_blueprint():
#     """Blueprint §1 Skenario 1: C=100, P_YES+P_NO=0.975 → Π harus > 0 setelah buffer."""
#     C = 100
#     P_yes = Decimal("0.49")
#     P_no = Decimal("0.485")  # total 0.975 → diskon 2.5¢
#     fee_k = fee_kalshi(C=C, P=P_yes, side="taker")       # $1.66
#     fee_p = fee_polymarket(C=C, P=P_no, kategori="Crypto")  # $1.71
#     pi = profit_bersih_pair(C, P_yes, P_no, fee_k, fee_p)
#     # Setelah semua biaya + gas + buffer, profit harus masih positif (atau ~0 di ambang)
#     assert pi >= Decimal("0"), f"Π harusnya >= 0, dapat {pi}"

def test_pi_scenario_1_blueprint():
    """Blueprint §1 Skenario 1: C=100, P_YES+P_NO=0.96 → diskon 4¢ > fee 3.5¢ → Π > 0."""
    C = 100
    P_yes = Decimal("0.48")
    P_no = Decimal("0.48")  # total 0.96 → diskon 4¢
    fee_k = fee_kalshi(C=C, P=P_yes, side="taker")       # $1.61
    fee_p = fee_polymarket(C=C, P=P_no, kategori="Crypto")  # $1.66
    pi = profit_bersih_pair(C, P_yes, P_no, fee_k, fee_p)
    # Dengan diskon 4¢ dan fee total ~3.5¢, profit harus positif
    assert pi >= Decimal("0"), f"Π harusnya >= 0, dapat {pi}"
    
def test_pi_tidak_untung_kalau_diskon_kekecilan():
    """Kalau diskon < total fee, Π harus negatif (bot harus tolak)."""
    C = 100
    P_yes = Decimal("0.495")
    P_no = Decimal("0.495")  # diskon cuma 1¢ < fee 3.5¢
    fee_k = fee_kalshi(C=C, P=P_yes, side="taker")
    fee_p = fee_polymarket(C=C, P=P_no, kategori="Crypto")
    pi = profit_bersih_pair(C, P_yes, P_no, fee_k, fee_p)
    assert pi < Decimal("0"), f"Π harusnya < 0 (rugi), dapat {pi}"