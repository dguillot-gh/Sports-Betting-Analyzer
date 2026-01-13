
import collections
import collections.abc
for name in ['MutableSet', 'MutableMapping', 'Mapping', 'Iterable', 'Callable', 'Sequence']:
    if not hasattr(collections, name):
        setattr(collections, name, getattr(collections.abc, name))

import sys
import os
from pathlib import Path

# Add backend to path
sys.path.append(str(Path.cwd()))
sys.path.append(str(Path.cwd() / "backend"))

from backend.scripts.ncaab_predictor import NCAABPredictor

def test_prediction():
    predictor = NCAABPredictor()
    # Test with some common teams
    teams = [
        ("Duke", "North Carolina"),
        ("Kansas", "Kentucky"),
        ("Gonzaga", "UCLA"),
        ("Purdue", "Indiana")
    ]
    
    for home, away in teams:
        print(f"\nAnalyzing: {away} @ {home}")
        res = predictor.predict_game(home, away)
        print(f"  Predicted Winner: {res['predicted_winner']}")
        print(f"  Predicted Total: {res['predicted_total']}")
        print(f"  Home Prob: {res['home_win_probability']}")
        
        home_stats = predictor.get_team_stats(home)
        away_stats = predictor.get_team_stats(away)
        print(f"  Home Stats: ppg={home_stats.get('ppg')}, games={home_stats.get('data_games', 0)}")
        print(f"  Away Stats: ppg={away_stats.get('ppg')}, games={away_stats.get('data_games', 0)}")

if __name__ == "__main__":
    test_prediction()
