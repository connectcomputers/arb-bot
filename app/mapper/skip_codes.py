"""
Kode alasan skip (tidak di-lock) sesuai blueprint v1.1.1.
"""
from enum import Enum


class SkipCode(str, Enum):
    S1 = "S1"  # Market hanya ada di satu venue
    S2 = "S2"  # Sumber/oracle settlement berbeda
    S3 = "S3"  # Jendela/cut-off waktu settlement berbeda
    S4 = "S4"  # Definisi outcome berbeda (false-friend)
    S5 = "S5"  # Placement delay aktif (sports live)
    S6 = "S6"  # Likuiditas di bawah minimum
    S7 = "S7"  # TTL < 60 detik ke settlement
    S8 = "S8"  # Market halted/delisted
    S9 = "S9"  # Parlay/non-biner (tidak cocok arbitrase)
    S10 = "S10"  # Tidak bisa di-parse ke canonical key
    S11 = "S11"  # Kategori dikecualikan (excluded)
    
    @property
    def description(self) -> str:
        return {
            SkipCode.S1: "Pasar hanya ada di satu bursa",
            SkipCode.S2: "Sumber/oracle settlement berbeda",
            SkipCode.S3: "Jendela/cut-off settlement berbeda",
            SkipCode.S4: "Definisi outcome berbeda (false-friend)",
            SkipCode.S5: "Placement delay aktif (3 detik)",
            SkipCode.S6: "Likuiditas di bawah minimum",
            SkipCode.S7: "TTL < 60 detik ke settlement",
            SkipCode.S8: "Market halted/delisted",
            SkipCode.S9: "Parlay/non-biner (tidak cocok arbitrase)",
            SkipCode.S10: "Tidak bisa di-parse ke canonical key",
            SkipCode.S11: "Kategori dikecualikan",
        }[self]


# Kategori yang TIDAK BOLEH di-arbitrase (hard-excluded)
EXCLUDED_CATEGORIES = {
    "Sports",        # Live sport = delay 3 detik
    "Entertainment", # Terlalu subjektif
    "Culture",       # Definisi outcome sering ambigu
}

# Template yang TIDAK BOLEH (non-biner)
EXCLUDED_TEMPLATES = {
    "PARLAY",        # Judi gabungan
    "MULTI_OUTCOME", # Lebih dari 2 outcome
}