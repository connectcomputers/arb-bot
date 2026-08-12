"""
Unit test Telegram alert — aman, tidak kirim real.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock

from app.alerts.telegram import send_opportunity_alert, _format_message


def test_format_message_berisi_semua_info_penting():
    """Pesan harus berisi key, venue, harga, Π, TTL."""
    msg = _format_message(
        key_str="BTC.UP_DOWN.15m",
        venues="POLYMARKET × KALSHI",
        direction="YES_A_NO_B",
        p1=Decimal("0.45"),
        p2=Decimal("0.50"),
        pi=Decimal("1.23"),
        size=100,
        ttl_hours=2.5,
        poly_url="https://polymarket.com/event/abc",
        kalshi_url="https://kalshi.com/markets/def",
    )
    
    assert "BTC.UP_DOWN.15m" in msg
    assert "POLYMARKET × KALSHI" in msg
    assert "YES_A_NO_B" in msg
    assert "0.450" in msg
    assert "0.500" in msg
    assert "$1.23" in msg
    assert "2.5 jam" in msg
    assert "polymarket.com" in msg
    assert "kalshi.com" in msg


def test_format_message_tanpa_url_juga_ok():
    """Pesan harus tetap valid kalau URL kosong."""
    msg = _format_message(
        key_str="TEST", venues="V1 × V2", direction="X",
        p1=Decimal("0.5"), p2=Decimal("0.5"),
        pi=Decimal("0"), size=100, ttl_hours=0,
    )
    assert "TEST" in msg


def test_send_skip_bila_tidak_ada_token():
    """Bila BOT_TOKEN kosong, harus return False tanpa error (test sync karena mode=auto)."""
    import asyncio
    
    with patch("app.alerts.telegram.BOT_TOKEN", ""), \
         patch("app.alerts.telegram.CHAT_ID", ""):
        result = asyncio.run(send_opportunity_alert(
            "KEY", "V", "DIR",
            Decimal("0.5"), Decimal("0.5"),
            Decimal("1"), 100, 1.0,
        ))
    assert result is False


def test_send_berhasil_bila_token_valid_mock():
    """Simulasi kirim sukses dengan mock httpx (test sync karena mode=auto)."""
    import asyncio
    from unittest.mock import patch, MagicMock
    
    with patch("app.alerts.telegram.BOT_TOKEN", "fake-token"), \
         patch("app.alerts.telegram.CHAT_ID", "123"):
        
        # Mock httpx.AsyncClient sebagai context manager sync
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        
        # Jadikan .post() coroutine yang resolve ke mock_response
        async def fake_post(*args, **kwargs):
            return mock_response
        
        mock_client.post = fake_post
        
        # Jadikan context manager mengembalikan mock_client
        class FakeCM:
            async def __aenter__(self):
                return mock_client
            async def __aexit__(self, *args):
                pass
        
        with patch("app.alerts.telegram.httpx.AsyncClient", return_value=FakeCM()):
            result = asyncio.run(send_opportunity_alert(
                "KEY", "V", "DIR",
                Decimal("0.5"), Decimal("0.5"),
                Decimal("1"), 100, 1.0,
            ))
    
    assert result is True