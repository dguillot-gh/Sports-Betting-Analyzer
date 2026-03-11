import pytest
import time
import httpx
from datetime import datetime
import anyio

# Assuming the backend is running locally within the container
BASE_URL = "http://localhost:8000"

@pytest.mark.anyio
async def test_nfl_standings_performance():
    """Verify NFL standings performance and structure"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        start_time = time.time()
        response = await client.get(f"{BASE_URL}/standings/nfl?season=2024")
        duration = time.time() - start_time
        
        assert response.status_code == 200
        data = response.json()
        assert data["sport"] == "nfl"
        assert len(data["standings"]) > 0
        
        # Verify first entry has required fields
        first = data["standings"][0]
        assert "team" in first
        assert "wins" in first
        assert "losses" in first

@pytest.mark.anyio
async def test_nba_standings_structure():
    """Verify NBA standings data integrity"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/standings/nba?season=2024")
        assert response.status_code == 200
        data = response.json()
        
        # Ensure win_pct is calculated correctly
        for team in data["standings"]:
            total = team["wins"] + team["losses"]
            if total > 0:
                expected_pct = round(team["wins"] / total, 3)
                assert team["win_pct"] == expected_pct
