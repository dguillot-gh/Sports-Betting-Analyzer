"""
PyNASCAR Adapter - Wrapper for pynascar package
Provides access to NASCAR race data, schedules, lap times, and driver stats.

Package: pip install pynascar
Source: GitHub pynascar
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import json

logger = logging.getLogger(__name__)

# Try to import pynascar
try:
    from pynascar import Schedule, Race, DriversData
    PYNASCAR_AVAILABLE = True
    logger.info("pynascar package loaded successfully")
except ImportError:
    PYNASCAR_AVAILABLE = False
    logger.warning("pynascar not installed - NASCAR live data unavailable")


class PyNASCARAdapter:
    """
    Adapter for pynascar package functionality.
    Provides schedule, race data, and driver statistics.
    """
    
    def __init__(self):
        self.cache = {}
        self.series_map = {
            "cup": "NASCAR Cup Series",
            "xfinity": "NASCAR Xfinity Series",
            "trucks": "NASCAR Craftsman Truck Series"
        }
        # pynascar uses series_id: 1=Cup, 2=Xfinity, 3=Trucks
        self.series_id_map = {
            "cup": 1,
            "xfinity": 2,
            "trucks": 3
        }
    
    def is_available(self) -> bool:
        """Check if pynascar is available."""
        return PYNASCAR_AVAILABLE
    
    def get_schedule(self, year: int = None, series: str = "cup") -> Dict:
        """
        Get race schedule for a season.
        
        Args:
            year: Season year (default: current year)
            series: 'cup', 'xfinity', or 'trucks' (note: pynascar may only support cup)
        """
        if not PYNASCAR_AVAILABLE:
            return {"error": "pynascar not installed", "install": "pip install pynascar"}
        
        if year is None:
            year = datetime.now().year
        
        cache_key = f"schedule_{year}_{series}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            # pynascar Schedule requires year and series_id
            series_id = self.series_id_map.get(series, 1)  # Default to Cup
            schedule = Schedule(year, series_id)
            
            races = []
            if hasattr(schedule, 'races'):
                for race in schedule.races:
                    races.append({
                        "race_id": getattr(race, 'race_id', None),
                        "name": getattr(race, 'name', 'Unknown'),
                        "track": getattr(race, 'track', 'Unknown'),
                        "date": str(getattr(race, 'date', '')),
                        "status": getattr(race, 'status', 'scheduled')
                    })
            
            result = {
                "year": year,
                "series": series,
                "series_name": self.series_map.get(series, series),
                "races": races,
                "count": len(races)
            }
            
            self.cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"Error fetching schedule: {e}")
            return {"error": str(e), "year": year, "series": series}
    
    def get_race_data(self, race_id: int) -> Dict:
        """
        Get detailed data for a specific race.
        
        Includes: results, lap times, pit stops, cautions
        """
        if not PYNASCAR_AVAILABLE:
            return {"error": "pynascar not installed"}
        
        cache_key = f"race_{race_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            race = Race(race_id=race_id)
            
            result = {
                "race_id": race_id,
                "name": getattr(race, 'name', 'Unknown'),
                "track": getattr(race, 'track', 'Unknown'),
                "date": str(getattr(race, 'date', '')),
                "status": getattr(race, 'status', 'unknown'),
                "laps_completed": getattr(race, 'laps_completed', 0),
                "total_laps": getattr(race, 'total_laps', 0),
            }
            
            # Get results if available
            if hasattr(race, 'results'):
                result["results"] = []
                for r in race.results[:20]:  # Top 20
                    result["results"].append({
                        "position": getattr(r, 'position', None),
                        "driver": getattr(r, 'driver', 'Unknown'),
                        "team": getattr(r, 'team', 'Unknown'),
                        "car_number": getattr(r, 'car_number', ''),
                        "laps_completed": getattr(r, 'laps_completed', 0),
                        "status": getattr(r, 'status', '')
                    })
            
            # Get lap times (summary)
            if hasattr(race, 'lap_times'):
                result["lap_times_available"] = True
                result["fastest_lap"] = getattr(race, 'fastest_lap', None)
            
            # Get pit stops
            if hasattr(race, 'pit_stops'):
                result["pit_stops_count"] = len(race.pit_stops) if race.pit_stops else 0
            
            # Get cautions
            if hasattr(race, 'cautions'):
                result["cautions"] = []
                for c in race.cautions:
                    result["cautions"].append({
                        "lap": getattr(c, 'lap', 0),
                        "reason": getattr(c, 'reason', 'Unknown')
                    })
            
            self.cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"Error fetching race data: {e}")
            return {"error": str(e), "race_id": race_id}
    
    def get_lap_times(self, race_id: int, driver: str = None) -> Dict:
        """
        Get lap times for a race, optionally filtered by driver.
        """
        if not PYNASCAR_AVAILABLE:
            return {"error": "pynascar not installed"}
        
        try:
            race = Race(race_id=race_id)
            
            if not hasattr(race, 'lap_times') or not race.lap_times:
                return {"error": "Lap times not available for this race", "race_id": race_id}
            
            lap_times = []
            for lt in race.lap_times:
                if driver and getattr(lt, 'driver', '') != driver:
                    continue
                lap_times.append({
                    "lap": getattr(lt, 'lap', 0),
                    "driver": getattr(lt, 'driver', 'Unknown'),
                    "time": getattr(lt, 'time', 0),
                    "position": getattr(lt, 'position', 0)
                })
            
            return {
                "race_id": race_id,
                "driver": driver,
                "lap_times": lap_times[:500],  # Limit for performance
                "count": len(lap_times)
            }
            
        except Exception as e:
            logger.error(f"Error fetching lap times: {e}")
            return {"error": str(e)}
    
    def get_pit_stops(self, race_id: int) -> Dict:
        """Get pit stop data for a race."""
        if not PYNASCAR_AVAILABLE:
            return {"error": "pynascar not installed"}
        
        try:
            race = Race(race_id=race_id)
            
            if not hasattr(race, 'pit_stops') or not race.pit_stops:
                return {"error": "Pit stop data not available", "race_id": race_id}
            
            pit_stops = []
            for ps in race.pit_stops:
                pit_stops.append({
                    "lap": getattr(ps, 'lap', 0),
                    "driver": getattr(ps, 'driver', 'Unknown'),
                    "duration": getattr(ps, 'duration', 0),
                    "position_in": getattr(ps, 'position_in', 0),
                    "position_out": getattr(ps, 'position_out', 0)
                })
            
            return {
                "race_id": race_id,
                "pit_stops": pit_stops,
                "count": len(pit_stops)
            }
            
        except Exception as e:
            logger.error(f"Error fetching pit stops: {e}")
            return {"error": str(e)}
    
    def get_driver_stats(self, year: int = None, series: str = "cup") -> Dict:
        """
        Get aggregated driver statistics for a season.
        """
        if not PYNASCAR_AVAILABLE:
            return {"error": "pynascar not installed"}
        
        if year is None:
            year = datetime.now().year
        
        try:
            # pynascar DriversData requires year and series_id
            series_id = self.series_id_map.get(series, 1)  # Default to Cup
            drivers_data = DriversData(year, series_id)
            
            drivers = []
            if hasattr(drivers_data, 'drivers'):
                for d in drivers_data.drivers:
                    drivers.append({
                        "driver": getattr(d, 'name', 'Unknown'),
                        "team": getattr(d, 'team', 'Unknown'),
                        "car_number": getattr(d, 'car_number', ''),
                        "points": getattr(d, 'points', 0),
                        "wins": getattr(d, 'wins', 0),
                        "top5": getattr(d, 'top5', 0),
                        "top10": getattr(d, 'top10', 0),
                        "avg_finish": getattr(d, 'avg_finish', 0),
                        "dnf": getattr(d, 'dnf', 0)
                    })
            
            return {
                "year": year,
                "series": series,
                "series_name": self.series_map.get(series, series),
                "drivers": drivers,
                "count": len(drivers)
            }
            
        except Exception as e:
            logger.error(f"Error fetching driver stats: {e}")
            return {"error": str(e)}
    
    def get_live_race(self) -> Dict:
        """
        Get data for currently live race if any.
        """
        if not PYNASCAR_AVAILABLE:
            return {"error": "pynascar not installed"}
        
        try:
            # Get current year schedule (pynascar requires year and series_id)
            schedule = Schedule(datetime.now().year, 1)  # 1 = Cup Series
            
            # Look for in-progress race
            if hasattr(schedule, 'races'):
                for race in schedule.races:
                    if getattr(race, 'status', '') == 'in_progress':
                        return self.get_race_data(race.race_id)
            
            return {"message": "No live race currently", "status": "no_live_race"}
            
        except Exception as e:
            logger.error(f"Error checking live race: {e}")
            return {"error": str(e)}


# Module-level instance
_adapter = None

def get_nascar_adapter() -> PyNASCARAdapter:
    """Get singleton adapter instance."""
    global _adapter
    if _adapter is None:
        _adapter = PyNASCARAdapter()
    return _adapter


# Convenience functions for API endpoints
def get_nascar_schedule(year: int = None, series: str = "cup") -> Dict:
    return get_nascar_adapter().get_schedule(year, series)

def get_nascar_race(race_id: int) -> Dict:
    return get_nascar_adapter().get_race_data(race_id)

def get_nascar_lap_times(race_id: int, driver: str = None) -> Dict:
    return get_nascar_adapter().get_lap_times(race_id, driver)

def get_nascar_pit_stops(race_id: int) -> Dict:
    return get_nascar_adapter().get_pit_stops(race_id)

def get_nascar_drivers(year: int = None, series: str = "cup") -> Dict:
    return get_nascar_adapter().get_driver_stats(year, series)

def get_nascar_live() -> Dict:
    return get_nascar_adapter().get_live_race()

def is_pynascar_available() -> bool:
    return PYNASCAR_AVAILABLE


if __name__ == "__main__":
    if PYNASCAR_AVAILABLE:
        adapter = PyNASCARAdapter()
        print("Testing pynascar adapter...")
        schedule = adapter.get_schedule(2024, "cup")
        print(json.dumps(schedule, indent=2, default=str))
    else:
        print("pynascar not installed. Run: pip install pynascar")
