import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from sports.nascar import NASCARSport

class SimulationEngine:
    def __init__(self, sport: NASCARSport):
        self.sport = sport
        self.model = None # Placeholder for ML model if needed
        
    def calculate_driver_strength(self, driver_id: str, year: int, track_type: str) -> float:
        """
        Calculate a driver's strength rating based on recent history, track type, and qualifying ability.
        Returns a float where 1.0 is average, >1.0 is better.
        """
        # Get stats for the specific year
        stats_data = self.sport.get_entity_stats(driver_id, year)
        
        # If no stats for this year (e.g. future year simulation), try previous year
        if not stats_data or not stats_data.get('stats') or stats_data['stats'].get('Races', 0) == 0:
            stats_data = self.sport.get_entity_stats(driver_id, year - 1)
            
        if not stats_data or 'stats' not in stats_data or stats_data['stats'].get('Races', 0) == 0:
            return 0.5 # Default low rating for unknown drivers
            
        stats = stats_data['stats']
        splits = stats_data.get('splits', {})
        history = stats_data.get('history', [])
        
        # 1. Base Strength (Overall Avg Finish)
        avg_finish = float(stats.get('Avg Finish', 20.0))
        base_strength = 20.0 / max(avg_finish, 1.0)
        
        # 2. Recency Bias (Last 5 races)
        recency_strength = base_strength
        if history:
            recent_finishes = [float(r['Finish']) for r in history[:5] if r['Finish'] != 'N/A']
            if recent_finishes:
                recent_avg = sum(recent_finishes) / len(recent_finishes)
                recency_strength = 20.0 / max(recent_avg, 1.0)
        
        # 3. Track Specificity
        track_strength = base_strength
        
        # Map UI track types to data track types
        lookup_type = track_type
        if track_type == "Road Course":
            lookup_type = "road"
        elif track_type in ["Intermediate", "Short Track", "Superspeedway", "Flat", "Concrete"]:
            # Fallback to 'paved' if specific type not found, but prefer specific if available
            if track_type not in splits and "paved" in splits:
                lookup_type = "paved"

        if lookup_type in splits:
            split_avg = float(splits[lookup_type].get('Avg Finish', avg_finish))
            track_strength = 20.0 / max(split_avg, 1.0)
            
        # 4. Qualifying Ability (Avg Start)
        # Better qualifiers often have better equipment/track position
        avg_start = float(stats.get('Avg Start', 20.0))
        qualifying_factor = 1.0 + (20.0 - avg_start) * 0.005 # Small boost/penalty
        
        # Weighted Combination
        # Base: 40%, Recency: 30%, Track: 30%
        combined_strength = (base_strength * 0.4) + (recency_strength * 0.3) + (track_strength * 0.3)
        
        # Apply qualifying factor
        final_strength = combined_strength * qualifying_factor
        
        return final_strength

    def _simulate_stage(self, current_order: List[str], strengths: Dict[str, float], variance: float = 0.5) -> List[str]:
        """
        Simulate a race segment/stage.
        """
        scores = {}
        for i, driver in enumerate(current_order):
            # Base score from strength
            base_score = strengths.get(driver, 0.5)
            
            # Position bonus (it's harder to pass, so being in front helps)
            # Bonus decreases as you go back
            pos_bonus = (len(current_order) - i) * 0.01
            
            # Random noise (Gumbel distribution)
            noise = np.random.gumbel(0, variance)
            
            scores[driver] = base_score + pos_bonus + noise
            
        # Sort by score descending
        return sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    def _simulate_single_race(self, strengths: Dict[str, float]) -> List[str]:
        """
        Simulate a full race with 3 stages and pit stops.
        """
        drivers = list(strengths.keys())
        
        # Initial shuffle (Qualifying/Start)
        # We'll assume starting order is somewhat correlated to strength but with high variance
        current_order = self._simulate_stage(drivers, strengths, variance=1.0)
        
        # Stage 1
        current_order = self._simulate_stage(current_order, strengths, variance=0.6)
        
        # Stage 2 (Pit stops introduce variance)
        # Shuffle order slightly to simulate pit stops
        # We add random noise to the current indices to reorder
        pit_noise = np.random.normal(0, 2, len(drivers)) # Standard deviation of 2 positions
        pit_order_scores = {d: -i + pit_noise[i] for i, d in enumerate(current_order)}
        current_order = sorted(pit_order_scores.keys(), key=lambda x: pit_order_scores[x], reverse=True)
        
        current_order = self._simulate_stage(current_order, strengths, variance=0.6)
        
        # Final Stage (More variance for late race restarts/strategy)
        # Another pit cycle
        pit_noise = np.random.normal(0, 2, len(drivers))
        pit_order_scores = {d: -i + pit_noise[i] for i, d in enumerate(current_order)}
        current_order = sorted(pit_order_scores.keys(), key=lambda x: pit_order_scores[x], reverse=True)
        
        final_order = self._simulate_stage(current_order, strengths, variance=0.5)
        
        return final_order

    def run_monte_carlo(self, drivers: List[str], year: int, track_type: str, num_simulations: int = 1000) -> Dict[str, Any]:
        """
        Run multiple simulations and aggregate results.
        """
        # Pre-calculate strengths to avoid repeated lookups
        strengths = {}
        for driver in drivers:
            strengths[driver] = self.calculate_driver_strength(driver, year, track_type)

        results = {driver: [] for driver in drivers}
        
        for _ in range(num_simulations):
            finishing_order = self._simulate_single_race(strengths)
            for pos, driver in enumerate(finishing_order):
                results[driver].append(pos + 1) # 1-based finish position
                
        # Aggregate stats
        aggregated = []
        for driver, finishes in results.items():
            finishes_array = np.array(finishes)
            agg = {
                "driver": driver,
                "avg_finish": float(np.mean(finishes_array)),
                "win_prob": float(np.mean(finishes_array == 1)),
                "top_5_prob": float(np.mean(finishes_array <= 5)),
                "top_10_prob": float(np.mean(finishes_array <= 10)),
                "best_finish": int(np.min(finishes_array)),
                "worst_finish": int(np.max(finishes_array))
            }
            aggregated.append(agg)
            
        # Sort by win probability descending
        aggregated.sort(key=lambda x: x['win_prob'], reverse=True)
        
        return {
            "metadata": {
                "year": year,
                "track_type": track_type,
                "simulations": num_simulations,
                "driver_count": len(drivers)
            },
            "results": aggregated
        }
