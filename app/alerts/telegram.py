"""
Telegram Alert — Minggu 8.3.
Mengirim notifikasi saat signal engine memutuskan 🟢 EKSEKUSI.

Aman: bila BOT_TOKEN/CHAT_ID kosong, fungsi send tidak error — hanya log warning.
"""
import os
from decimal import Decimal
from typing import Optional

import httpx
from dotenv import load_dotenv

# Muat .env (kalau ada)
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TELEGRAM_API = "https://api.telegram.org"


def _format_message(
    key_str: str,
    venues: str,
    direction: str,
    p1: Decimal,
    p2: Decimal,
    pi: Decimal,
    size: int,
    ttl_hours: float,
    poly_url: str = "",
    kalshi_url: str = "",
) -> str:
    """Format pesan Telegram yang informatif & mudah dibaca."""
    return (
        f"🎯 <b>PELUANG ARBITRASE TERDETEKSI</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>{key_str}</b>\n"
        f"🏢 {venues}\n"
        f"🧭 Arah: <code>{direction}</code>\n"
        f"\n"
        f"💵 Harga kaki:\n"
        f"  • Kaki 1: {p1:.3f}\n"
        f"  • Kaki 2: {p2:.3f}\n"
        f"\n"
        f"📊 Π netto (C={size}): <b>${pi:.2f}</b>\n"
        f"⏱ TTL: {ttl_hours:.1f} jam\n"
        f"\n"
        f"🔗 Lihat market:\n"
        + (f"  • Polymarket: {poly_url}\n" if poly_url else "")
        + (f"  • Kalshi: {kalshi_url}\n" if kalshi_url else "")
        + f"\n"
        f"📝 <i>Order paper sudah dicatat di data/paper_trades.json</i>"
    )


async def send_opportunity_alert(
    key_str: str,
    venues: str,
    direction: str,
    p1: Decimal,
    p2: Decimal,
    pi: Decimal,
    size: int = 100,
    ttl_hours: float = 0.0,
    poly_url: str = "",
    kalshi_url: str = "",
) -> bool:
    """
    Kirim alert ke Telegram. Return True kalau sukses, False kalau gagal/skip.
    Tidak error bila BOT_TOKEN/CHAT_ID kosong (mode dev).
    """
    if not BOT_TOKEN or not CHAT_ID:
        # Mode dev: tidak kirim, return False tanpa error
        return False
    
    text = _format_message(
        key_str, venues, direction, p1, p2, pi, size, ttl_hours,
        poly_url, kalshi_url,
    )
    
    url = f"{TELEGRAM_API}/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("ok", False)
            return False
    except Exception:
        return False

async def send_text(text: str) -> bool:
    """Kirim pesan teks bebas (untuk alert konflik settlement)."""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"{6762674507}/bot{8886412853:AAHO6a160Fy03TwwS1VkYcXxwvsfqfRfLi8}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            )
            return resp.status_code == 200 and resp.json().get("ok", False)
    except Exception:
        return False
    