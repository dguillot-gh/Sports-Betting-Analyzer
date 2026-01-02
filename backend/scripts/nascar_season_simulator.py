"""
NASCAR Season Simulator
Simulates full NASCAR seasons (Cup/Xfinity/Trucks) with playoff system.
"""

import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class NASCARSeasonSimulator:
    """
    Simulates entire NASCAR seasons with:
    - Regular season (26 races for Cup)
    - Playoffs (10 races for Cup)
    - Points system with stage points
    - Championship 4 final race
    """
    
    # NASCAR 2024+ schedule templates by series
    SCHEDULE = {
        "cup": {
            "regular_season_races": 26,
            "playoff_races": 10,
            "playoff_drivers": 16,
            "track_types": [
                "Superspeedway", "Short Track", "Intermediate", "Road Course",
                "Superspeedway", "Intermediate", "Short Track", "Road Course",
                "Intermediate", "Superspeedway", "Short Track", "Intermediate",
                "Road Course", "Intermediate", "Intermediate", "Short Track",
                "Intermediate", "Road Course", "Intermediate", "Intermediate",
                "Intermediate", "Short Track", "Superspeedway", "Road Course",
                "Short Track", "Intermediate",  # End regular season
                # Playoffs
                "Superspeedway", "Short Track", "Road Course",  # Round of 16
                "Intermediate", "Short Track", "Road Course",    # Round of 12
                "Intermediate", "Intermediate", "Short Track",   # Round of 8
                "Intermediate"  # Championship 4
            ]
        },
        "xfinity": {
            "regular_season_races": 26,
            "playoff_races": 7,
            "playoff_drivers": 12,
            "track_types": None  # Will mirror cup with some variation
        },
        "trucks": {
            "regular_season_races": 16,
            "playoff_races": 7,
            "playoff_drivers": 10,
            "track_types": None
        }
    }
    
    # Points system
    RACE_POINTS = [40, 35, 34, 33, 32, 31, 30, 29, 28, 27, 
                   26, 25, 24, 23, 22, 21, 20, 19, 18, 17,
                   16, 15, 14, 13, 12, 11, 10, 9, 8, 7,
                   6, 5, 4, 3, 2, 1, 1, 1, 1, 1]
    
    STAGE_POINTS = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    
    def __init__(self, drivers: List[str], series: str = "cup"):
        self.drivers = drivers
        self.series = series.lower()
        self.schedule = self.SCHEDULE.get(self.series, self.SCHEDULE["cup"])
        
    def _get_driver_strength(self, driver: str, track_type: str) -> float:
        """
        Get driver strength for track type.
        In real implementation, this would use historical data.
        For now, uses a consistent random seed per driver for stability.
        """
        # Create consistent strength based on driver name
        seed = sum(ord(c) for c in driver)
        np.random.seed(seed)
        base_strength = np.random.uniform(0.5, 1.5)
        
        # Track-specific adjustments
        track_seed = seed + sum(ord(c) for c in track_type)
        np.random.seed(track_seed)
        track_modifier = np.random.uniform(0.8, 1.2)
        
        np.random.seed(None)  # Reset seed
        return base_strength * track_modifier
    
    def _simulate_race(self, track_type: str, strengths: Dict[str, float]) -> List[str]:
        """Simulate a single race, returns finishing order."""
        scores = {}
        for driver in self.drivers:
            base = strengths.get(driver, 1.0)
            noise = np.random.gumbel(0, 0.5)
            scores[driver] = base + noise
        
        return sorted(scores.keys(), key=lambda d: scores[d], reverse=True)
    
    def _calculate_race_points(self, finish_position: int, won_stage1: bool = False, 
                               won_stage2: bool = False, won_race: bool = False) -> int:
        """Calculate points for a race finish."""
        if finish_position > len(self.RACE_POINTS):
            base_points = 1
        else:
            base_points = self.RACE_POINTS[finish_position - 1]
        
        # Stage points (simplified - award to top 10 in stages)
        stage_points = 0
        if won_stage1:
            stage_points += 10
        if won_stage2:
            stage_points += 10
        if won_race:
            stage_points += 5  # Playoff point for win
            
        return base_points + stage_points
    
    def simulate_season(self, num_simulations: int = 100) -> Dict[str, Any]:
        """
        Run full season simulation.
        Returns championship probabilities, playoff odds, etc.
        """
        logger.info(f"Running {num_simulations} {self.series} season simulations...")
        
        championships = {d: 0 for d in self.drivers}
        playoff_appearances = {d: 0 for d in self.drivers}
        championship_4 = {d: 0 for d in self.drivers}
        wins = {d: 0 for d in self.drivers}
        avg_points = {d: [] for d in self.drivers}
        
        # Pre-calculate strengths for each track type
        track_types = ["Superspeedway", "Short Track", "Intermediate", "Road Course"]
        strengths_by_track = {}
        for track in track_types:
            strengths_by_track[track] = {d: self._get_driver_strength(d, track) for d in self.drivers}
        
        for sim in range(num_simulations):
            # Track season results
            points = {d: 0 for d in self.drivers}
            race_wins = {d: 0 for d in self.drivers}
            
            total_races = self.schedule["regular_season_races"] + self.schedule["playoff_races"]
            schedule = self.schedule.get("track_types") or ["Intermediate"] * total_races
            
            # === REGULAR SEASON ===
            for race_num in range(self.schedule["regular_season_races"]):
                track_type = schedule[race_num % len(schedule)]
                
                # Simulate race
                result = self._simulate_race(track_type, strengths_by_track.get(track_type, {}))
                
                # Award points
                for pos, driver in enumerate(result):
                    pts = self._calculate_race_points(pos + 1, won_race=(pos == 0))
                    points[driver] += pts
                    if pos == 0:
                        race_wins[driver] += 1
                        wins[driver] += 1
            
            # Save regular season points for avg calculation
            for d in self.drivers:
                avg_points[d].append(points[d])
            
            # === DETERMINE PLAYOFF FIELD ===
            # Winners auto-qualify, then by points
            winners = [d for d in self.drivers if race_wins[d] > 0]
            non_winners = [d for d in self.drivers if race_wins[d] == 0]
            non_winners.sort(key=lambda d: points[d], reverse=True)
            
            playoff_field = winners[:self.schedule["playoff_drivers"]]
            spots_remaining = self.schedule["playoff_drivers"] - len(playoff_field)
            playoff_field.extend(non_winners[:spots_remaining])
            
            for d in playoff_field:
                playoff_appearances[d] += 1
            
            # === PLAYOFFS ===
            # Simplified: Just simulate playoff races and track who makes Champ 4
            playoff_points = {d: points[d] for d in playoff_field}
            
            # Simulate playoff races
            playoff_start = self.schedule["regular_season_races"]
            for race_num in range(self.schedule["playoff_races"] - 1):  # All but final
                track_idx = playoff_start + race_num
                track_type = schedule[track_idx % len(schedule)]
                
                result = self._simulate_race(track_type, strengths_by_track.get(track_type, {}))
                
                for pos, driver in enumerate(result):
                    if driver in playoff_points:
                        pts = self._calculate_race_points(pos + 1, won_race=(pos == 0))
                        playoff_points[driver] += pts
            
            # Championship 4 = top 4 in points entering final race
            sorted_playoff = sorted(playoff_points.keys(), key=lambda d: playoff_points[d], reverse=True)
            champ_4 = sorted_playoff[:4]
            
            for d in champ_4:
                championship_4[d] += 1
            
            # === CHAMPIONSHIP RACE ===
            # Winner of final race among Champ 4 wins title
            final_track = schedule[-1] if schedule else "Intermediate"
            final_result = self._simulate_race(final_track, strengths_by_track.get(final_track, {}))
            
            # Find highest finisher among Champ 4
            for driver in final_result:
                if driver in champ_4:
                    championships[driver] += 1
                    break
        
        # Calculate probabilities
        results = []
        for driver in self.drivers:
            results.append({
                "driver": driver,
                "championship_pct": round(championships[driver] / num_simulations * 100, 1),
                "champ_4_pct": round(championship_4[driver] / num_simulations * 100, 1),
                "playoff_pct": round(playoff_appearances[driver] / num_simulations * 100, 1),
                "avg_wins": round(wins[driver] / num_simulations, 2),
                "avg_points": round(np.mean(avg_points[driver]), 1) if avg_points[driver] else 0
            })
        
        # Sort by championship probability
        results.sort(key=lambda x: x["championship_pct"], reverse=True)
        
        return {
            "series": self.series.upper(),
            "simulations": num_simulations,
            "generated_at": datetime.now().isoformat(),
            "drivers": len(self.drivers),
            "results": results
        }
    
    def simulate_single_race(self, race_num: int, track_type: str, num_simulations: int = 500) -> Dict[str, Any]:
        """
        Simulate a single race and return win/top5/top10 probabilities.
        Useful for race-by-race betting predictions.
        """
        # Pre-calculate strengths
        strengths = {d: self._get_driver_strength(d, track_type) for d in self.drivers}
        
        results = {d: {"wins": 0, "top5": 0, "top10": 0, "finishes": []} for d in self.drivers}
        
        for _ in range(num_simulations):
            race_result = self._simulate_race(track_type, strengths)
            
            for pos, driver in enumerate(race_result):
                results[driver]["finishes"].append(pos + 1)
                if pos == 0:
                    results[driver]["wins"] += 1
                if pos < 5:
                    results[driver]["top5"] += 1
                if pos < 10:
                    results[driver]["top10"] += 1
        
        # Calculate probabilities
        predictions = []
        for driver, data in results.items():
            avg_finish = np.mean(data["finishes"]) if data["finishes"] else 20
            predictions.append({
                "driver": driver,
                "win_pct": round(data["wins"] / num_simulations * 100, 1),
                "top5_pct": round(data["top5"] / num_simulations * 100, 1),
                "top10_pct": round(data["top10"] / num_simulations * 100, 1),
                "avg_finish": round(avg_finish, 1)
            })
        
        # Sort by win probability
        predictions.sort(key=lambda x: x["win_pct"], reverse=True)
        
        return {
            "race_num": race_num,
            "track_type": track_type,
            "simulations": num_simulations,
            "predictions": predictions
        }
    
    def simulate_all_races(self, num_simulations: int = 200) -> Dict[str, Any]:
        """
        Simulate all races in the season with predictions for each.
        Returns per-race win/top5/top10 probabilities.
        """
        total_races = self.schedule["regular_season_races"] + self.schedule["playoff_races"]
        schedule = self.schedule.get("track_types") or ["Intermediate"] * total_races
        
        # NASCAR 2025 Schedule (simplified)
        race_names = self._get_race_schedule()
        
        all_races = []
        
        for race_num in range(total_races):
            track_type = schedule[race_num % len(schedule)]
            race_name = race_names[race_num] if race_num < len(race_names) else f"Race {race_num + 1}"
            
            race_prediction = self.simulate_single_race(race_num + 1, track_type, num_simulations)
            race_prediction["race_name"] = race_name
            race_prediction["is_playoff"] = race_num >= self.schedule["regular_season_races"]
            
            all_races.append(race_prediction)
        
        return {
            "series": self.series.upper(),
            "total_races": total_races,
            "simulations_per_race": num_simulations,
            "generated_at": datetime.now().isoformat(),
            "races": all_races
        }
    
    def _get_race_schedule(self) -> List[str]:
        """Get race names for the season."""
        if self.series == "cup":
            return [
                "Daytona 500", "Atlanta", "Las Vegas", "Phoenix", "Bristol Dirt",
                "COTA", "Richmond", "Martinsville", "Texas", "Talladega",
                "Dover", "Kansas", "Darlington", "Charlotte", "Gateway",
                "Sonoma", "Nashville", "Chicago Street", "Pocono", "New Hampshire",
                "Pocono 2", "Richmond 2", "Michigan", "Indianapolis", "Watkins Glen",
                "Daytona Night",  # End Regular Season
                # Playoffs
                "Atlanta Playoff", "Watkins Glen Playoff", "Bristol Night",
                "Kansas Playoff", "Talladega Playoff", "Charlotte Roval",
                "Las Vegas Playoff", "Homestead", "Martinsville Playoff",
                "Phoenix Championship"
            ]
        elif self.series == "xfinity":
            return [f"Xfinity Race {i+1}" for i in range(33)]
        else:
            return [f"Truck Race {i+1}" for i in range(23)]


# Default driver lists by series (fallback if API unavailable)
DEFAULT_DRIVERS = {
    "cup": [
        "Kyle Larson", "William Byron", "Chase Elliott", "Ryan Blaney",
        "Denny Hamlin", "Christopher Bell", "Tyler Reddick", "Joey Logano",
        "Martin Truex Jr.", "Ross Chastain", "Brad Keselowski", "Chris Buescher",
        "Bubba Wallace", "Alex Bowman", "Kyle Busch", "Austin Cindric",
        "Ty Gibbs", "Noah Gragson", "Daniel Suarez", "Michael McDowell",
        "Austin Dillon", "Chase Briscoe", "Erik Jones", "Ricky Stenhouse Jr.",
        "Todd Gilliland", "Josh Berry", "Carson Hocevar", "Corey LaJoie"
    ],
    "xfinity": [
        "Cole Custer", "Justin Allgaier", "Austin Hill", "Sam Mayer",
        "Sheldon Creed", "Riley Herbst", "Brandon Jones", "Jesse Love",
        "Chandler Smith", "John Hunter Nemechek", "AJ Allmendinger", "Josh Williams"
    ],
    "trucks": [
        "Christian Eckes", "Corey Heim", "Nick Sanchez", "Ty Majeski",
        "Ben Rhodes", "Grant Enfinger", "Rajah Caruth", "Tanner Gray",
        "Stewart Friesen", "Matt Crafton", "Tyler Ankrum", "Dean Thompson"
    ]
}


async def get_drivers_from_data(series: str = "cup") -> List[str]:
    """
    Try to get drivers from the existing NASCAR data API.
    Falls back to default list if unavailable.
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://localhost:8000/nascar/drivers",
                params={"series": series},
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 10:
                    logger.info(f"Loaded {len(data)} drivers from API for {series}")
                    return data[:40]  # Limit to top 40
    except Exception as e:
        logger.warning(f"Could not fetch drivers from API: {e}")
    
    return DEFAULT_DRIVERS.get(series.lower(), DEFAULT_DRIVERS["cup"])


async def run_nascar_season_simulation(
    series: str = "cup",
    num_simulations: int = 100,
    custom_drivers: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Run NASCAR season simulation.
    
    Args:
        series: "cup", "xfinity", or "trucks"
        num_simulations: Number of seasons to simulate
        custom_drivers: Optional custom driver list
    """
    if custom_drivers:
        drivers = custom_drivers
    else:
        # Try to get from data API, fall back to defaults
        drivers = await get_drivers_from_data(series)
    
    simulator = NASCARSeasonSimulator(drivers, series)
    return simulator.simulate_season(num_simulations)


if __name__ == "__main__":
    import asyncio
    
    async def test():
        result = asyncio.run(run_nascar_season_simulation("cup", 50))
        print(json.dumps(result, indent=2))
    
    asyncio.run(test())
