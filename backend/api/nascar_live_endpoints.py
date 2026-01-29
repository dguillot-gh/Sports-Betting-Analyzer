"""
NASCAR Live Dashboard API (Ported from VMI1994/Nascar-Live-Dashboard)
Provides specific data format for the RaceDash live dashboard.
Isolates deep logic (laps led, deltas, sponsors) from the main API to ensure stability.
"""

from fastapi import APIRouter
import httpx
from datetime import timedelta
import time
import json
from typing import Dict, List, Any

router = APIRouter(prefix="/nascar-live", tags=["NASCAR Live"])

LIVE_FEED_URL = "https://cf.nascar.com/live/feeds/live-feed.json"

class RacingDashboardLogic:
    """
    Encapsulates logic ported from VMI1994/webdash.py
    """
    
    def compute_laps_led_count(self, laps_led):
        count = 0
        for period in laps_led:
            count += period.get('end_lap', 0) - period.get('start_lap', 0) + 1
        return count
    
    def format_delta(self, delta):
        if delta == 0:
            return "-"
        return f"{delta:.3f}"

    def process_feed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process raw NASCAR feed into Dashboard-ready format.
        """
        # Process race info
        race_info = {}
        for key, value in data.items():
            if key not in ['vehicles', 'stage']:
                if key == 'elapsed_time':
                    # Simple formatting, could use timedelta
                    pass 
                race_info[key] = value
        
        if 'stage' in data:
            race_info['stage'] = str(data['stage'])

        # Process vehicles
        vehicles = data.get('vehicles', [])
        leader_elapsed = vehicles[0].get('vehicle_elapsed_time', 0) if vehicles else 0
        vehicles_data = []

        for idx, vehicle in enumerate(vehicles, start=1):
            driver = vehicle.get('driver', {})
            driver_name = driver.get('full_name', 'N/A')
            laps_led = vehicle.get('laps_led', [])
            laps_led_count = self.compute_laps_led_count(laps_led)
            pit_stops_count = len(vehicle.get('pit_stops', []))
            
            # Recalculate delta exactly as webdash.py does
            # vehicle.get('delta') sometimes is pre-calculated, but fallback to elapsed calc
            raw_delta = vehicle.get('delta')
            if raw_delta is None:
                 raw_delta = vehicle.get('vehicle_elapsed_time', 0) - leader_elapsed
            
            delta_str = self.format_delta(raw_delta)

            # Extract fields with safe defaults matching the original dashboard
            vehicles_data.append({
                'Position': idx,
                'Number': vehicle.get('vehicle_number', 'N/A'),
                'Driver': driver_name,
                'Starting Pos': vehicle.get('starting_position', 'N/A'),
                'Running Pos': vehicle.get('running_position', idx),
                'Status': vehicle.get('status', 'N/A'),
                'Laps Completed': vehicle.get('laps_completed', 'N/A'),
                'Delta': delta_str,
                'Last Lap Time': f"{vehicle.get('last_lap_time', 0):.3f}",
                'Last Lap Speed': f"{vehicle.get('last_lap_speed', 0):.3f}",
                'Best Lap Time': f"{vehicle.get('best_lap_time', 0):.3f}",
                'Best Lap Speed': f"{vehicle.get('best_lap_speed', 0):.3f}",
                'Average Speed': f"{vehicle.get('average_speed', 0):.3f}",
                'Fastest Laps': vehicle.get('fastest_laps_run', 'N/A'),
                'Laps Led Count': laps_led_count,
                'Pit Stops': pit_stops_count,
                'On Track': vehicle.get('is_on_track', 'N/A'),
                'Sponsor': vehicle.get('sponsor_name', 'N/A'),
                'Manufacturer': vehicle.get('vehicle_manufacturer', 'N/A')
            })

        return {
            'race_info': race_info,
            'vehicles': vehicles_data
        }

_logic = RacingDashboardLogic()

@router.get("/dashboard-data")
async def get_dashboard_data():
    """
    Endpoint dedicated to the Live Dashboard page.
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(LIVE_FEED_URL, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            return _logic.process_feed(data)
        except Exception as e:
            return {"error": str(e)}
