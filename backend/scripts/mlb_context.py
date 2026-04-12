"""
MLB Context Data
=================
Park factors, weather fetching, and venue metadata for MLB predictions.
"""

import logging
from datetime import date
from typing import Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ============================================================================
# PARK FACTORS (2024 season averages, 1.0 = league average)
# Higher = more runs. Source: ESPN Park Factors / FanGraphs
# ============================================================================
PARK_FACTORS: Dict[str, float] = {
    # AL East
    "Yankee Stadium": 1.09,
    "Fenway Park": 1.07,
    "Oriole Park at Camden Yards": 1.02,
    "Rogers Centre": 1.04,
    "Tropicana Field": 0.91,
    # AL Central
    "Guaranteed Rate Field": 1.06,
    "Progressive Field": 0.98,
    "Comerica Park": 0.93,
    "Kauffman Stadium": 1.00,
    "Target Field": 1.01,
    # AL West
    "Globe Life Field": 0.99,
    "Angel Stadium": 0.96,
    "T-Mobile Park": 0.93,
    "Oakland Coliseum": 0.94,
    "Minute Maid Park": 1.04,
    # NL East
    "Citizens Bank Park": 1.10,
    "Citi Field": 0.93,
    "Nationals Park": 1.02,
    "Truist Park": 0.99,
    "loanDepot park": 0.93,
    # NL Central
    "Wrigley Field": 1.06,
    "Great American Ball Park": 1.11,
    "American Family Field": 1.02,
    "Busch Stadium": 0.96,
    "PNC Park": 0.92,
    # NL West
    "Coors Field": 1.38,
    "Petco Park": 0.92,
    "Dodger Stadium": 0.98,
    "Oracle Park": 0.86,
    "Chase Field": 1.05,
}

# Dome / retractable roof venues (weather irrelevant for indoor games)
DOME_VENUES = {
    "Tropicana Field",
    "Globe Life Field",
    "loanDepot park",
    "Minute Maid Park",   # retractable
    "American Family Field",  # retractable
    "Chase Field",        # retractable
    "T-Mobile Park",      # retractable
    "Rogers Centre",      # retractable
}

# Venue lat/lon for weather API lookups
VENUE_COORDS: Dict[str, tuple] = {
    "Yankee Stadium": (40.8296, -73.9262),
    "Fenway Park": (42.3467, -71.0972),
    "Oriole Park at Camden Yards": (39.2838, -76.6216),
    "Rogers Centre": (43.6414, -79.3894),
    "Tropicana Field": (27.7682, -82.6534),
    "Guaranteed Rate Field": (41.8300, -87.6339),
    "Progressive Field": (41.4962, -81.6852),
    "Comerica Park": (42.3390, -83.0485),
    "Kauffman Stadium": (39.0517, -94.4803),
    "Target Field": (44.9818, -93.2775),
    "Globe Life Field": (32.7512, -97.0832),
    "Angel Stadium": (33.8003, -117.8827),
    "T-Mobile Park": (47.5914, -122.3325),
    "Oakland Coliseum": (37.7516, -122.2006),
    "Minute Maid Park": (29.7572, -95.3555),
    "Citizens Bank Park": (39.9061, -75.1665),
    "Citi Field": (40.7571, -73.8458),
    "Nationals Park": (38.8731, -77.0074),
    "Truist Park": (33.8907, -84.4677),
    "loanDepot park": (25.7781, -80.2196),
    "Wrigley Field": (41.9484, -87.6553),
    "Great American Ball Park": (39.0975, -84.5069),
    "American Family Field": (43.0280, -87.9712),
    "Busch Stadium": (38.6226, -90.1928),
    "PNC Park": (40.4468, -80.0058),
    "Coors Field": (39.7559, -104.9942),
    "Petco Park": (32.7076, -117.1570),
    "Dodger Stadium": (34.0739, -118.2400),
    "Oracle Park": (37.7786, -122.3893),
    "Chase Field": (33.4455, -112.0667),
}


def get_park_factor(venue_name: str) -> float:
    """Get park factor for a venue (1.0 = league average)."""
    return PARK_FACTORS.get(venue_name, 1.0)


def is_dome(venue_name: str) -> bool:
    """Check if venue is a dome or retractable roof."""
    return venue_name in DOME_VENUES


# ============================================================================
# WEATHER (Open-Meteo API — free, no key required)
# ============================================================================

async def fetch_game_weather(
    venue_name: str,
    game_date: date = None,
    game_hour: int = 19,  # default 7 PM local
) -> Dict[str, Any]:
    """
    Fetch weather forecast for a game at the given venue.
    Uses Open-Meteo free API (no key needed, 10k calls/day).

    Returns dict with: temp_f, windspeed_mph, wind_direction, is_overcast
    """
    if is_dome(venue_name):
        return {
            "temp_f": 72.0,
            "windspeed_mph": 0.0,
            "wind_direction": 0,
            "is_dome": True,
            "is_overcast": False,
            "wind_out": False,
            "wind_in": False,
        }

    coords = VENUE_COORDS.get(venue_name)
    if not coords:
        return _default_weather()

    game_date = game_date or date.today()
    lat, lon = coords

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,windspeed_10m,winddirection_10m,cloudcover"
        f"&temperature_unit=fahrenheit&windspeed_unit=mph"
        f"&start_date={game_date}&end_date={game_date}"
        f"&timezone=America/New_York"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        hourly = data.get("hourly", {})
        temps = hourly.get("temperature_2m", [])
        winds = hourly.get("windspeed_10m", [])
        wind_dirs = hourly.get("winddirection_10m", [])
        clouds = hourly.get("cloudcover", [])

        # Pick the hour closest to game time
        idx = min(game_hour, len(temps) - 1) if temps else 0

        temp = temps[idx] if idx < len(temps) else 72.0
        wind = winds[idx] if idx < len(winds) else 0.0
        wind_dir = wind_dirs[idx] if idx < len(wind_dirs) else 0
        cloud = clouds[idx] if idx < len(clouds) else 0

        return {
            "temp_f": round(temp, 1),
            "windspeed_mph": round(wind, 1),
            "wind_direction": wind_dir,
            "is_dome": False,
            "is_overcast": cloud > 75,
            "temp_cold": temp < 50,
            "temp_hot": temp > 90,
            "wind_out": _is_wind_out(wind_dir, wind),
            "wind_in": _is_wind_in(wind_dir, wind),
        }

    except Exception as e:
        logger.warning(f"Weather fetch failed for {venue_name}: {e}")
        return _default_weather()


def _default_weather() -> Dict[str, Any]:
    return {
        "temp_f": 72.0,
        "windspeed_mph": 5.0,
        "wind_direction": 0,
        "is_dome": False,
        "is_overcast": False,
        "temp_cold": False,
        "temp_hot": False,
        "wind_out": False,
        "wind_in": False,
    }


def _is_wind_out(direction: int, speed: float) -> bool:
    """Wind blowing out to center field (roughly 180-270°) with >= 10 mph."""
    return speed >= 10 and 150 <= direction <= 300


def _is_wind_in(direction: int, speed: float) -> bool:
    """Wind blowing in from outfield (roughly 0-60° or 300-360°) with >= 10 mph."""
    return speed >= 10 and (direction <= 60 or direction >= 300)
