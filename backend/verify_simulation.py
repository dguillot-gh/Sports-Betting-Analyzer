import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from sport_factory import SportFactory
from simulation import SimulationEngine

def verify_simulation():
    print("Initializing SportFactory...")
    sport, _ = SportFactory.get_sport('nascar')
    
    engine = SimulationEngine(sport)
    
    drivers = ["Kyle Larson", "Denny Hamlin", "Chase Elliott", "William Byron", "Ryan Blaney"]
    year = 2023
    track_type = "Intermediate"
    
    print(f"Running simulation for {year} {track_type} with {len(drivers)} drivers...")
    results = engine.run_monte_carlo(drivers, year, track_type, num_simulations=100)
    
    print("\nSimulation Results:")
    for res in results['results']:
        print(f"{res['driver']}: Win% {res['win_prob']:.1%}, Top5% {res['top_5_prob']:.1%}, Avg Finish {res['avg_finish']:.1f}")
        
    print("\nVerification Complete.")

if __name__ == "__main__":
    verify_simulation()
