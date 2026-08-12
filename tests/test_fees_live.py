"""Unit test Live-Fee Fetch (mock API responses)."""
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock

from app.fees_live import (
    fetch_kalshi_fee_live,
    fetch_polymarket_fee_live,
    fetch_limitless_fee_schedule_live,
)

@pytest.fixture(autouse=True)
def _clean_cache():
    """Pastikan setiap test mulai dengan cache kosong."""
    from app.fees_live import clear_cache
    clear_cache()
    yield
    clear_cache()
    
@pytest.mark.asyncio
async def test_kalshi_fee_live_success():
    """Kalshi fee fetch sukses → return fee rate dari API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "taker_fee_bps": 5,
        "is_non_standard": False,
    }
    
    with patch("app.fees_live.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        MockClient.return_value = mock_client
        
        result = await fetch_kalshi_fee_live("KXFED-26SEP")
        assert result["fee_rate"] == Decimal("0.0005")
        assert result["is_non_standard"] is False


@pytest.mark.asyncio
async def test_kalshi_fee_live_fallback():
    """Kalshi fee fetch gagal → fallback ke default 0.07."""
    with patch("app.fees_live.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client.__aenter__.return_value = mock_client
        MockClient.return_value = mock_client
        
        result = await fetch_kalshi_fee_live("KXFED-26SEP")
        assert result["fee_rate"] == Decimal("0.07")


@pytest.mark.asyncio
async def test_polymarket_fee_live_success():
    """Polymarket fee fetch sukses → return fee rate dari API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"fee_rate": 0.04}
    
    with patch("app.fees_live.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        MockClient.return_value = mock_client
        
        result = await fetch_polymarket_fee_live("abc123")
        assert result["fee_rate"] == Decimal("0.04")


@pytest.mark.asyncio
async def test_limitless_fee_schedule_live_success():
    """Limitless fee schedule fetch sukses → return schedule dari API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "buy": [[0.50, 0.03]],
        "sell": [[0.01, 0.0042]],
        "amm": 0.004,
    }
    
    with patch("app.fees_live.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        MockClient.return_value = mock_client
        
        result = await fetch_limitless_fee_schedule_live()
        assert len(result["buy"]) == 1
        assert result["amm"] == Decimal("0.004")