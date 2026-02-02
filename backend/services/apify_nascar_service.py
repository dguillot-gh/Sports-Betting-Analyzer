"""
Apify DraftKings NASCAR Odds Service

Fetches NASCAR betting odds from DraftKings via Apify's DraftKings API Actor.
Free tier: $5/month credits (enough for several daily runs).

Setup:
1. Create free Apify account at https://apify.com
2. Get API token from Settings > Integrations
3. Set APIFY_API_TOKEN in .env
"""

import os
import httpx
import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
# Correct actor ID from Apify marketplace
DRAFTKINGS_ACTOR_ID = "mherzog~draftkings-sportsbook-odds"  # Note: ~ not / for actor path

# Cache to avoid burning credits
_odds_cache: Dict = {}
_cache_timestamp: Optional[datetime] = None
CACHE_DURATION = timedelta(minutes=30)


async def fetch_nascar_odds_from_apify() -> List[Dict]:
    """
    Fetch NASCAR odds from DraftKings via Apify.
    Returns list of driver odds objects.
    """
    global _odds_cache, _cache_timestamp
    
    # Return cached data if valid
    if _cache_timestamp and (datetime.now() - _cache_timestamp) < CACHE_DURATION:
        logger.info("Returning cached NASCAR odds")
        return _odds_cache.get("drivers", [])
    
    if not APIFY_API_TOKEN:
        logger.warning("APIFY_API_TOKEN not set - cannot fetch NASCAR odds")
        return []
    
    try:
        # Apify Actor API endpoint
        url = f"https://api.apify.com/v2/acts/{DRAFTKINGS_ACTOR_ID}/run-sync-get-dataset-items"
        
        # Input for the mherzog/draftkings-sportsbook-odds actor
        # This actor scrapes all sports - we'll filter NASCAR in parse
        actor_input = {
            "sport": "motorsports",  # DraftKings category for NASCAR
            "startUrls": [
                {"url": "https://sportsbook.draftkings.com/leagues/motorsports/nascar"}
            ],
            "maxConcurrency": 1
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                params={"token": APIFY_API_TOKEN},
                json=actor_input,
                headers={"Content-Type": "application/json"}
            )
            
            # 200 and 201 are both success codes for Apify
            if response.status_code in (200, 201):
                data = response.json()
                if not data:
                    logger.warning("Apify returned empty dataset - DraftKings may not have NASCAR odds available yet")
                    return []
                drivers = parse_draftkings_response(data)
                
                # Cache the results
                _odds_cache = {"drivers": drivers, "source": "draftkings"}
                _cache_timestamp = datetime.now()
                
                logger.info(f"Fetched {len(drivers)} NASCAR driver odds from DraftKings")
                return drivers
            elif response.status_code == 402:
                logger.error("Apify credits exhausted - upgrade plan or wait for reset")
                return []
            else:
                logger.error(f"Apify API error: {response.status_code} - {response.text[:500]}")
                return []
                
    except Exception as e:
        logger.error(f"Failed to fetch NASCAR odds from Apify: {e}")
        return []


def parse_draftkings_response(data: List[Dict]) -> List[Dict]:
    """
    Parse Apify/DraftKings response into standardized driver odds format.
    """
    drivers = []
    
    for item in data:
        try:
            # DraftKings format may vary - adapt as needed
            driver_name = item.get("name") or item.get("participant") or item.get("selection", "Unknown")
            odds = item.get("odds") or item.get("price") or item.get("americanOdds")
            
            if not driver_name or not odds:
                continue
            
            # Format odds string
            if isinstance(odds, (int, float)):
                odds_str = f"+{int(odds)}" if odds > 0 else str(int(odds))
            else:
                odds_str = str(odds)
            
            drivers.append({
                "driver_name": driver_name,
                "market_odds": odds_str,
                "car_number": item.get("carNumber", ""),
                "team": item.get("team", ""),
                "source": "draftkings",
                "fetched_at": datetime.now().isoformat()
            })
        except Exception as e:
            logger.warning(f"Error parsing driver: {e}")
            continue
    
    # Sort by odds (favorites first)
    drivers.sort(key=lambda x: _parse_odds_value(x.get("market_odds", "+99999")))
    
    # Add rank
    for i, d in enumerate(drivers, 1):
        d["rank"] = i
    
    return drivers


def _parse_odds_value(odds_str: str) -> int:
    """Parse American odds string to sortable value (lower = more likely)."""
    try:
        val = int(odds_str.replace("+", ""))
        return val if val > 0 else abs(val) - 10000  # Negative odds are favorites
    except:
        return 99999


async def get_driver_market_odds(driver_name: str) -> Optional[str]:
    """
    Get market odds for a specific driver.
    """
    drivers = await fetch_nascar_odds_from_apify()
    
    target = driver_name.lower().strip()
    for d in drivers:
        if target in d.get("driver_name", "").lower():
            return d.get("market_odds")
    
    return None


def clear_cache():
    """Clear the odds cache."""
    global _odds_cache, _cache_timestamp
    _odds_cache = {}
    _cache_timestamp = None
