
import httpx
import os
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from src.config import ODDS_API_KEY

class NascarOddsService:
    # Updated sport key based on API documentation
    BASE_URL = "https://api.the-odds-api.com/v4/sports/motorsport_nascar_cup_series/odds"
    # Fallback/Base URL for sports discovery if needed
    # BASE_URL_GENERIC = "https://api.the-odds-api.com/v4/sports/motorsport_nascar/odds"
    CACHE_DURATION = timedelta(minutes=15)  # Cache for 15 minutes to save API calls
    
    def __init__(self):
        self._cache = None
        self._last_update = None
        self._api_key = ODDS_API_KEY

    async def get_live_odds(self) -> List[Dict]:
        """
        Fetch live NASCAR odds. Tries The Odds API first, falls back to Apify/DraftKings.
        Returns a list of race odds objects.
        """
        # Return cached data if valid
        if self._cache and self._last_update:
            if datetime.now() - self._last_update < self.CACHE_DURATION:
                return self._cache

        # Try The Odds API first
        if self._api_key:
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
                        data = response.json()
                        if data:  # Only cache if we got data
                            self._cache = data
                            self._last_update = datetime.now()
                            return self._cache
                    else:
                        print(f"Odds API Error: {response.status_code} - {response.text}")
                        
            except Exception as e:
                print(f"The Odds API failed: {e}")

        # Fallback to Apify/DraftKings
        try:
            from services.apify_nascar_service import fetch_nascar_odds_from_apify
            drivers = await fetch_nascar_odds_from_apify()
            if drivers:
                self._cache = drivers
                self._last_update = datetime.now()
                return self._cache
        except Exception as e:
            print(f"Apify fallback failed: {e}")
        
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
