"""
NASCAR Schedule Data
Contains schedules for Cup, Xfinity, and Trucks series.
Supports multiple years - update each year when official schedules are released.

2026 Schedule: Will be released ~August 2026. Update this file then.
"""

from typing import List, Dict
from datetime import date

CURRENT_YEAR = 2026  # Update this when new schedules are added

# 2025 NASCAR Cup Series Schedule
NASCAR_CUP_2025 = [
    {"race": 1, "name": "Daytona 500", "track": "Daytona International Speedway", "track_type": "Superspeedway", "date": "2025-02-16", "is_playoff": False},
    {"race": 2, "name": "Atlanta 400", "track": "Atlanta Motor Speedway", "track_type": "Superspeedway", "date": "2025-02-23", "is_playoff": False},
    {"race": 3, "name": "Las Vegas 400", "track": "Las Vegas Motor Speedway", "track_type": "Intermediate", "date": "2025-03-02", "is_playoff": False},
    {"race": 4, "name": "Phoenix 500", "track": "Phoenix Raceway", "track_type": "Short Track", "date": "2025-03-09", "is_playoff": False},
    {"race": 5, "name": "Bristol Dirt Race", "track": "Bristol Motor Speedway (Dirt)", "track_type": "Short Track", "date": "2025-03-23", "is_playoff": False},
    {"race": 6, "name": "COTA 400", "track": "Circuit of the Americas", "track_type": "Road Course", "date": "2025-03-30", "is_playoff": False},
    {"race": 7, "name": "Richmond 400", "track": "Richmond Raceway", "track_type": "Short Track", "date": "2025-04-06", "is_playoff": False},
    {"race": 8, "name": "Martinsville 500", "track": "Martinsville Speedway", "track_type": "Short Track", "date": "2025-04-13", "is_playoff": False},
    {"race": 9, "name": "Texas 500", "track": "Texas Motor Speedway", "track_type": "Intermediate", "date": "2025-04-20", "is_playoff": False},
    {"race": 10, "name": "Talladega 500", "track": "Talladega Superspeedway", "track_type": "Superspeedway", "date": "2025-04-27", "is_playoff": False},
    {"race": 11, "name": "Dover 400", "track": "Dover Motor Speedway", "track_type": "Intermediate", "date": "2025-05-04", "is_playoff": False},
    {"race": 12, "name": "Kansas 400", "track": "Kansas Speedway", "track_type": "Intermediate", "date": "2025-05-11", "is_playoff": False},
    {"race": 13, "name": "Darlington 500", "track": "Darlington Raceway", "track_type": "Intermediate", "date": "2025-05-18", "is_playoff": False},
    {"race": 14, "name": "Coca-Cola 600", "track": "Charlotte Motor Speedway", "track_type": "Intermediate", "date": "2025-05-25", "is_playoff": False},
    {"race": 15, "name": "Gateway 300", "track": "World Wide Technology Raceway", "track_type": "Intermediate", "date": "2025-06-01", "is_playoff": False},
    {"race": 16, "name": "Sonoma 350", "track": "Sonoma Raceway", "track_type": "Road Course", "date": "2025-06-08", "is_playoff": False},
    {"race": 17, "name": "Nashville 400", "track": "Nashville Superspeedway", "track_type": "Intermediate", "date": "2025-06-15", "is_playoff": False},
    {"race": 18, "name": "Chicago Street Race", "track": "Chicago Street Course", "track_type": "Road Course", "date": "2025-07-06", "is_playoff": False},
    {"race": 19, "name": "Pocono 400", "track": "Pocono Raceway", "track_type": "Superspeedway", "date": "2025-07-13", "is_playoff": False},
    {"race": 20, "name": "New Hampshire 301", "track": "New Hampshire Motor Speedway", "track_type": "Short Track", "date": "2025-07-20", "is_playoff": False},
    {"race": 21, "name": "Pocono 350", "track": "Pocono Raceway", "track_type": "Superspeedway", "date": "2025-07-27", "is_playoff": False},
    {"race": 22, "name": "Richmond 400", "track": "Richmond Raceway", "track_type": "Short Track", "date": "2025-08-03", "is_playoff": False},
    {"race": 23, "name": "Michigan 400", "track": "Michigan International Speedway", "track_type": "Intermediate", "date": "2025-08-10", "is_playoff": False},
    {"race": 24, "name": "Indianapolis 400", "track": "Indianapolis Motor Speedway", "track_type": "Intermediate", "date": "2025-08-17", "is_playoff": False},
    {"race": 25, "name": "Watkins Glen 335", "track": "Watkins Glen International", "track_type": "Road Course", "date": "2025-08-24", "is_playoff": False},
    {"race": 26, "name": "Daytona Coke Zero 400", "track": "Daytona International Speedway", "track_type": "Superspeedway", "date": "2025-08-31", "is_playoff": False},
    # Playoffs - Round of 16
    {"race": 27, "name": "Atlanta Playoff", "track": "Atlanta Motor Speedway", "track_type": "Superspeedway", "date": "2025-09-07", "is_playoff": True, "playoff_round": "Round of 16"},
    {"race": 28, "name": "Watkins Glen Playoff", "track": "Watkins Glen International", "track_type": "Road Course", "date": "2025-09-14", "is_playoff": True, "playoff_round": "Round of 16"},
    {"race": 29, "name": "Bristol Night Race", "track": "Bristol Motor Speedway", "track_type": "Short Track", "date": "2025-09-21", "is_playoff": True, "playoff_round": "Round of 16"},
    # Playoffs - Round of 12
    {"race": 30, "name": "Kansas Playoff", "track": "Kansas Speedway", "track_type": "Intermediate", "date": "2025-09-28", "is_playoff": True, "playoff_round": "Round of 12"},
    {"race": 31, "name": "Talladega Playoff", "track": "Talladega Superspeedway", "track_type": "Superspeedway", "date": "2025-10-05", "is_playoff": True, "playoff_round": "Round of 12"},
    {"race": 32, "name": "Charlotte Roval", "track": "Charlotte Motor Speedway Roval", "track_type": "Road Course", "date": "2025-10-12", "is_playoff": True, "playoff_round": "Round of 12"},
    # Playoffs - Round of 8
    {"race": 33, "name": "Las Vegas Playoff", "track": "Las Vegas Motor Speedway", "track_type": "Intermediate", "date": "2025-10-19", "is_playoff": True, "playoff_round": "Round of 8"},
    {"race": 34, "name": "Homestead 400", "track": "Homestead-Miami Speedway", "track_type": "Intermediate", "date": "2025-10-26", "is_playoff": True, "playoff_round": "Round of 8"},
    {"race": 35, "name": "Martinsville Playoff", "track": "Martinsville Speedway", "track_type": "Short Track", "date": "2025-11-02", "is_playoff": True, "playoff_round": "Round of 8"},
    # Championship
    {"race": 36, "name": "Phoenix Championship", "track": "Phoenix Raceway", "track_type": "Short Track", "date": "2025-11-09", "is_playoff": True, "playoff_round": "Championship 4"},
]

# Xfinity Series 2025 (simplified)
NASCAR_XFINITY_2025 = [
    {"race": i+1, "name": f"Xfinity Race {i+1}", "track": "Various", "track_type": "Intermediate", "date": f"2025-{(i//4)+2:02d}-{((i%4)*7)+1:02d}", "is_playoff": i >= 26}
    for i in range(33)
]

# Trucks Series 2025 (simplified)
NASCAR_TRUCKS_2025 = [
    {"race": i+1, "name": f"Truck Race {i+1}", "track": "Various", "track_type": "Intermediate", "date": f"2025-{(i//3)+2:02d}-{((i%3)*7)+1:02d}", "is_playoff": i >= 16}
    for i in range(23)
]

# 2026 Schedule Placeholder - Update when official schedule is released (~August 2026)
# For now, uses 2025 schedule structure with updated dates
def _generate_placeholder_schedule(schedule_prev: List[Dict], year: int) -> List[Dict]:
    """Generate placeholder schedule from previous year."""
    schedule_new = []
    for race in schedule_prev:
        race_new = race.copy()
        old_date = race["date"]
        race_new["date"] = old_date.replace(str(year-1), str(year))
        schedule_new.append(race_new)
    return schedule_new

# 2026 NASCAR Cup Series Schedule (OFFICIAL)
NASCAR_CUP_2026 = [
    # February
    {"race": 1, "name": "Daytona 500", "track": "Daytona International Speedway", "track_type": "Superspeedway", "date": "2026-02-15", "is_playoff": False},
    {"race": 2, "name": "Atlanta 400", "track": "Atlanta Motor Speedway", "track_type": "Superspeedway", "date": "2026-02-22", "is_playoff": False},
    # March
    {"race": 3, "name": "COTA 400", "track": "Circuit of the Americas", "track_type": "Road Course", "date": "2026-03-01", "is_playoff": False},
    {"race": 4, "name": "Phoenix 500", "track": "Phoenix Raceway", "track_type": "Short Track", "date": "2026-03-08", "is_playoff": False},
    {"race": 5, "name": "Las Vegas 400", "track": "Las Vegas Motor Speedway", "track_type": "Intermediate", "date": "2026-03-15", "is_playoff": False},
    {"race": 6, "name": "Darlington 400", "track": "Darlington Raceway", "track_type": "Intermediate", "date": "2026-03-22", "is_playoff": False},
    {"race": 7, "name": "Martinsville 500", "track": "Martinsville Speedway", "track_type": "Short Track", "date": "2026-03-29", "is_playoff": False},
    # April
    {"race": 8, "name": "Bristol 500", "track": "Bristol Motor Speedway", "track_type": "Short Track", "date": "2026-04-12", "is_playoff": False},
    {"race": 9, "name": "Kansas 400", "track": "Kansas Speedway", "track_type": "Intermediate", "date": "2026-04-19", "is_playoff": False},
    {"race": 10, "name": "Talladega 500", "track": "Talladega Superspeedway", "track_type": "Superspeedway", "date": "2026-04-26", "is_playoff": False},
    # May
    {"race": 11, "name": "Texas 500", "track": "Texas Motor Speedway", "track_type": "Intermediate", "date": "2026-05-03", "is_playoff": False},
    {"race": 12, "name": "Watkins Glen 355", "track": "Watkins Glen International", "track_type": "Road Course", "date": "2026-05-10", "is_playoff": False},
    {"race": 13, "name": "Coca-Cola 600", "track": "Charlotte Motor Speedway", "track_type": "Intermediate", "date": "2026-05-24", "is_playoff": False},
    {"race": 14, "name": "Nashville 400", "track": "Nashville Superspeedway", "track_type": "Intermediate", "date": "2026-05-31", "is_playoff": False},
    # June
    {"race": 15, "name": "Michigan 400", "track": "Michigan International Speedway", "track_type": "Intermediate", "date": "2026-06-07", "is_playoff": False},
    {"race": 16, "name": "Pocono 400", "track": "Pocono Raceway", "track_type": "Superspeedway", "date": "2026-06-14", "is_playoff": False},
    {"race": 17, "name": "San Diego Street Race", "track": "Naval Base Coronado", "track_type": "Road Course", "date": "2026-06-21", "is_playoff": False},
    {"race": 18, "name": "Sonoma 350", "track": "Sonoma Raceway", "track_type": "Road Course", "date": "2026-06-28", "is_playoff": False},
    # July
    {"race": 19, "name": "Chicagoland 400", "track": "Chicagoland Speedway", "track_type": "Intermediate", "date": "2026-07-05", "is_playoff": False},
    {"race": 20, "name": "Atlanta 400", "track": "Atlanta Motor Speedway", "track_type": "Superspeedway", "date": "2026-07-12", "is_playoff": False},
    {"race": 21, "name": "North Wilkesboro 400", "track": "North Wilkesboro Speedway", "track_type": "Short Track", "date": "2026-07-19", "is_playoff": False},
    {"race": 22, "name": "Brickyard 400", "track": "Indianapolis Motor Speedway", "track_type": "Intermediate", "date": "2026-07-26", "is_playoff": False},
    # August
    {"race": 23, "name": "Iowa 350", "track": "Iowa Speedway", "track_type": "Short Track", "date": "2026-08-09", "is_playoff": False},
    {"race": 24, "name": "Richmond 400", "track": "Richmond Raceway", "track_type": "Short Track", "date": "2026-08-15", "is_playoff": False},
    {"race": 25, "name": "New Hampshire 301", "track": "New Hampshire Motor Speedway", "track_type": "Short Track", "date": "2026-08-23", "is_playoff": False},
    {"race": 26, "name": "Daytona Night Race", "track": "Daytona International Speedway", "track_type": "Superspeedway", "date": "2026-08-29", "is_playoff": False},
    # Playoffs - Round of 16
    {"race": 27, "name": "Darlington Playoff", "track": "Darlington Raceway", "track_type": "Intermediate", "date": "2026-09-06", "is_playoff": True, "playoff_round": "Round of 16"},
    {"race": 28, "name": "Gateway Playoff", "track": "World Wide Technology Raceway", "track_type": "Intermediate", "date": "2026-09-13", "is_playoff": True, "playoff_round": "Round of 16"},
    {"race": 29, "name": "Bristol Night Race", "track": "Bristol Motor Speedway", "track_type": "Short Track", "date": "2026-09-19", "is_playoff": True, "playoff_round": "Round of 16"},
    # Playoffs - Round of 12
    {"race": 30, "name": "Kansas Playoff", "track": "Kansas Speedway", "track_type": "Intermediate", "date": "2026-09-27", "is_playoff": True, "playoff_round": "Round of 12"},
    {"race": 31, "name": "Las Vegas Playoff", "track": "Las Vegas Motor Speedway", "track_type": "Intermediate", "date": "2026-10-04", "is_playoff": True, "playoff_round": "Round of 12"},
    {"race": 32, "name": "Charlotte Roval", "track": "Charlotte Motor Speedway Roval", "track_type": "Road Course", "date": "2026-10-11", "is_playoff": True, "playoff_round": "Round of 12"},
    # Playoffs - Round of 8
    {"race": 33, "name": "Phoenix Playoff", "track": "Phoenix Raceway", "track_type": "Short Track", "date": "2026-10-18", "is_playoff": True, "playoff_round": "Round of 8"},
    {"race": 34, "name": "Talladega Playoff", "track": "Talladega Superspeedway", "track_type": "Superspeedway", "date": "2026-10-25", "is_playoff": True, "playoff_round": "Round of 8"},
    {"race": 35, "name": "Martinsville Playoff", "track": "Martinsville Speedway", "track_type": "Short Track", "date": "2026-11-01", "is_playoff": True, "playoff_round": "Round of 8"},
    # Championship
    {"race": 36, "name": "Homestead Championship", "track": "Homestead-Miami Speedway", "track_type": "Intermediate", "date": "2026-11-08", "is_playoff": True, "playoff_round": "Championship 4"},
]

# Xfinity and Trucks 2026 (placeholder - use 2025 structure)
NASCAR_XFINITY_2026 = _generate_placeholder_schedule(NASCAR_XFINITY_2025, 2026)
NASCAR_TRUCKS_2026 = _generate_placeholder_schedule(NASCAR_TRUCKS_2025, 2026)

# Schedule lookup by year
SCHEDULES = {
    2025: {
        "cup": NASCAR_CUP_2025,
        "xfinity": NASCAR_XFINITY_2025,
        "trucks": NASCAR_TRUCKS_2025,
    },
    2026: {
        "cup": NASCAR_CUP_2026,
        "xfinity": NASCAR_XFINITY_2026,
        "trucks": NASCAR_TRUCKS_2026,
    }
}


def get_schedule(series: str = "cup", year: int = None) -> List[Dict]:
    """Get schedule for a NASCAR series and year."""
    if year is None:
        year = CURRENT_YEAR
    
    series = series.lower()
    year_schedules = SCHEDULES.get(year, SCHEDULES[CURRENT_YEAR])
    return year_schedules.get(series, year_schedules["cup"])


def get_next_race(series: str = "cup") -> Dict:
    """Get the next upcoming race."""
    schedule = get_schedule(series)
    today = date.today()
    
    for race in schedule:
        race_date = date.fromisoformat(race["date"])
        if race_date >= today:
            return race
    
    # If all races passed, return last race
    return schedule[-1] if schedule else {}


def get_remaining_races(series: str = "cup") -> List[Dict]:
    """Get all remaining races in the season."""
    schedule = get_schedule(series)
    today = date.today()
    
    return [r for r in schedule if date.fromisoformat(r["date"]) >= today]
