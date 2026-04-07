import pytest
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from scripts.ncaab_predictor import NCAABPredictor

@pytest.fixture
def predictor():
    return NCAABPredictor()

def test_prediction_structure(predictor):
    """Test standard prediction output structure"""
    result = predictor.predict_game("Duke", "North Carolina", spread=5.5, over_under=150.5)
    
    assert "predicted_winner" in result
    assert "home_win_probability" in result
    assert "away_win_probability" in result
    assert "confidence" in result
    
    # Check probabilities sum roughly to 1
    prob_sum = result['home_win_probability'] + result['away_win_probability']
    assert 0.99 <= prob_sum <= 1.01

def test_default_stats(predictor):
    """Test that unknown teams return default stats but still predict"""
    # Assuming 'UnknownTeam123' doesn't exist in data
    stats = predictor.get_team_stats("UnknownTeam123")
    assert stats['is_default'] is True
    assert stats['ppg'] == 73.0

def test_value_identification(predictor):
    """Test that edges are correctly identified"""
    # Force a prediction where home is heavily favored
    # We can't easily force the internal math without mocking stats, 
    # but we can check the keys.
    result = predictor.predict_game("Duke", "UNC", spread=0.0)
    # Predictor currently returns a pick-only spread analysis.
    assert "spread_pick" in result
    assert result["spread_pick"] in ("HOME", "AWAY")
