
import httpx
import os
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from src.config import ODDS_API_KEY

class NascarOddsService:
    BASE_URL = "https://api.the-odds-api.com/v4/sports/motorsport_nascar/odds"
    CACHE_DURATION = timedelta(minutes=15)  # Cache for 15 minutes to save API calls
    
    def __init__(self):
        self._cache = None
        self._last_update = None
        self._api_key = ODDS_API_KEY

    async def get_live_odds(self) -> List[Dict]:
        """
        Fetch live NASCAR odds from The Odds API.
        Returns a list of race odds objects.
        """
        if not self._api_key:
            return []
            
        # Return cached data if valid
        if self._cache and self._last_update:
            if datetime.now() - self._last_update < self.CACHE_DURATION:
                return self._cache

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "apiKey": self._api_key,
                        "regions": "us",
                        "markets": "h2h,outrights",
                        "oddsFormat": "american"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    self._cache = response.json()
                    self._last_update = datetime.now()
                    return self._cache
                else:
                    print(f"Odds API Error: {response.status_code} - {response.text}")
                    return []
                    
        except Exception as e:
            print(f"Failed to fetch NASCAR odds: {e}")
            return []

    async def get_driver_odds(self, driver_name: str) -> Optional[str]:
        """
        Find best available odds for a specific driver across all active markets.
        """
        odds_data = await self.get_live_odds()
        if not odds_data:
            return None
            
        # Normalize driver name for fuzzy matching (simplified)
        target_name = driver_name.lower().replace(".", "").strip()
        
        best_price = None
        best_odds_str = None
        
        for event in odds_data:
            for bookmaker in event.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    if market["key"] == "outrights":
                        for outcome in market.get("outcomes", []):
                            outcome_name = outcome["name"].lower().replace(".", "").strip()
                            
                            # Check for match (fuzzy match could be improved here)
                            if target_name in outcome_name or outcome_name in target_name:
                                price = outcome["price"]
                                # Find best odds (highest return)
                                if best_price is None or price > best_price:
                                    best_price = price
                                    # Format American odds
                                    if price > 0:
                                        best_odds_str = f"+{price}"
                                    else:
                                        best_odds_str = f"{price}"
                                        
        return best_odds_str
