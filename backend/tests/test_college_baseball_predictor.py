"""
Tests for college_baseball_predictor.py
Verifies that get_team_stats correctly aggregates per-player batting/pitching
CSVs and that predict_game produces real (non-dummy) predictions.
"""

import asyncio
import os
import pytest
from unittest.mock import patch, AsyncMock
from pathlib import Path

# ---------------------------------------------------------------------------
# Dummy CSV content matching the GitHub schema
# ---------------------------------------------------------------------------

DUMMY_BATTING_CSV = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,g,ab,pa,h,1b,2b,3b,hr,r,rbi,bb,so,hbp,sf,sh,gdp,sb,cs,avg,bb%,k%,bb/k,obp,slg,ops,iso,spd,babip,wsb,wrc,wraa,woba,wrc+
Player A,TST,Test University,21.0,Player A,10001,,2025,50,200,230,60,40,12,2,6,35,30,25,40,3,2,0,3,5,2,0.300,0.109,0.174,0.625,0.380,0.500,0.880,0.200,5.0,0.340,0.5,40.0,8.0,0.400,130.0
Player B,TST,Test University,22.0,Player B,10002,,2025,48,190,220,55,35,11,1,8,32,28,20,35,5,1,1,2,3,1,0.289,0.091,0.159,0.571,0.370,0.490,0.860,0.201,4.5,0.330,0.3,38.0,6.0,0.390,125.0
Player C,TST,Test University,20.0,Player C,10003,,2025,45,170,195,44,30,8,0,6,28,22,18,38,4,1,2,1,8,3,0.259,0.092,0.195,0.474,0.340,0.420,0.760,0.161,4.2,0.310,0.2,32.0,3.0,0.360,110.0
"""

DUMMY_PITCHING_CSV = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,w,l,era,g,gs,cg,sho,sv,ip,tbf,h,r,er,hr,bb,hbp,wp,bk,so,k/9,bb/9,k/bb,hr/9,k%,bb%,k-bb%,avg,whip,babip,lob%,fip,e-f
Pitcher X,TST,Test University,22.0,Pitcher X,20001,,2025,7,3,3.50,14,14,1,0,0,80.0,330,65,35,31,5,20,4,3,0,85,9.56,2.25,4.25,0.56,0.258,0.061,0.197,0.210,1.063,0.290,0.72,3.40,-0.10
Pitcher Y,TST,Test University,21.0,Pitcher Y,20002,,2025,4,2,4.20,12,10,0,0,0,60.0,260,55,30,28,4,18,3,2,0,55,8.25,2.70,3.06,0.60,0.212,0.069,0.143,0.230,1.217,0.300,0.68,4.10,0.10
Pitcher Z,TST,Test University,23.0,Pitcher Z,20003,,2025,2,0,2.10,20,0,0,0,8,30.0,120,18,8,7,1,8,2,1,0,35,10.50,2.40,4.38,0.30,0.292,0.067,0.225,0.170,0.867,0.260,0.80,2.80,-0.60
"""

# Second dummy team (opponent — weaker offense, worse pitching)
DUMMY_BATTING_CSV_2 = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,g,ab,pa,h,1b,2b,3b,hr,r,rbi,bb,so,hbp,sf,sh,gdp,sb,cs,avg,bb%,k%,bb/k,obp,slg,ops,iso,spd,babip,wsb,wrc,wraa,woba,wrc+
Player D,OPP,Opponent State,21.0,Player D,30001,,2025,52,210,240,50,34,10,1,5,25,20,22,50,4,2,1,4,2,1,0.238,0.092,0.208,0.440,0.320,0.380,0.700,0.142,3.8,0.300,0.1,28.0,1.0,0.330,95.0
Player E,OPP,Opponent State,22.0,Player E,30002,,2025,50,195,225,48,32,9,1,6,22,18,20,48,5,1,0,3,4,2,0.246,0.089,0.213,0.417,0.330,0.400,0.730,0.154,4.0,0.310,0.1,30.0,2.0,0.340,100.0
Player F,OPP,Opponent State,20.0,Player F,30003,,2025,40,160,180,35,25,6,0,4,18,15,15,42,3,1,1,2,6,2,0.219,0.083,0.233,0.357,0.300,0.350,0.650,0.131,3.5,0.280,0.0,22.0,-2.0,0.310,85.0
"""

DUMMY_PITCHING_CSV_2 = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,w,l,era,g,gs,cg,sho,sv,ip,tbf,h,r,er,hr,bb,hbp,wp,bk,so,k/9,bb/9,k/bb,hr/9,k%,bb%,k-bb%,avg,whip,babip,lob%,fip,e-f
Pitcher M,OPP,Opponent State,22.0,Pitcher M,40001,,2025,5,5,4.80,14,14,0,0,0,75.0,320,72,42,40,8,22,5,4,0,60,7.20,2.64,2.73,0.96,0.188,0.069,0.119,0.240,1.253,0.310,0.65,4.60,0.20
Pitcher N,OPP,Opponent State,21.0,Pitcher N,40002,,2025,3,4,5.10,12,10,0,0,0,55.0,245,58,35,31,6,20,3,3,0,40,6.55,3.27,2.00,0.98,0.163,0.082,0.082,0.250,1.418,0.320,0.60,5.20,0.10
"""


@pytest.fixture
def stats_dir(tmp_path):
    """Create a temporary stats directory with dummy CSV files."""
    stats = tmp_path / "stats"
    stats.mkdir()

    (stats / "Test_University_batting.csv").write_text(DUMMY_BATTING_CSV)
    (stats / "Test_University_pitching.csv").write_text(DUMMY_PITCHING_CSV)
    (stats / "Opponent_State_batting.csv").write_text(DUMMY_BATTING_CSV_2)
    (stats / "Opponent_State_pitching.csv").write_text(DUMMY_PITCHING_CSV_2)

    return stats


@pytest.fixture
def predictor(stats_dir):
    """Create a predictor that uses our test data directory."""
    import scripts.college_baseball_predictor as mod

    original = mod._find_data_dir
    mod._find_data_dir = lambda: stats_dir

    p = mod.CollegeBaseballPredictor()
    # Ensure XGBoost model paths don't exist to avoid loading
    p.use_xgb = False
    p.use_stat_xgb = False

    yield p

    mod._find_data_dir = original


def _run(coro):
    """Helper to run an async coroutine in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ======================================================================
# Tests for get_team_stats
# ======================================================================

class TestGetTeamStats:

    def test_batting_runs_aggregation(self, predictor):
        stats = _run(predictor.get_team_stats("Test University"))
        assert stats is not None
        # 35 + 32 + 28 = 95 total runs, 50 games
        assert stats['runs_per_game'] == pytest.approx(95 / 50, abs=0.1)

    def test_pitching_runs_allowed(self, predictor):
        stats = _run(predictor.get_team_stats("Test University"))
        assert stats is not None
        # 35 + 30 + 8 = 73 total RA, 50 games
        assert stats['runs_allowed'] == pytest.approx(73 / 50, abs=0.1)

    def test_win_pct_from_record(self, predictor):
        stats = _run(predictor.get_team_stats("Test University"))
        assert stats is not None
        # W=13, L=5, total decisions=18 >= 5
        assert stats['win_pct'] == pytest.approx(13 / 18, abs=0.01)

    def test_batting_rate_stats(self, predictor):
        stats = _run(predictor.get_team_stats("Test University"))
        assert stats is not None
        assert stats['avg'] > 0.2
        assert stats['obp'] > 0.3
        assert stats['slg'] > 0.3

    def test_pitching_rate_stats(self, predictor):
        stats = _run(predictor.get_team_stats("Test University"))
        assert stats is not None
        assert stats['era'] > 0
        assert stats['whip'] > 0
        assert stats['k9'] > 0

    def test_sample_size(self, predictor):
        stats = _run(predictor.get_team_stats("Test University"))
        assert stats is not None
        assert stats['sample_size'] == 50

    def test_missing_team_returns_none(self, predictor):
        stats = _run(predictor.get_team_stats("Nonexistent University"))
        assert stats is None

    def test_caching(self, predictor):
        s1 = _run(predictor.get_team_stats("Test University"))
        s2 = _run(predictor.get_team_stats("Test University"))
        assert s1 is s2


# ======================================================================
# Tests for predict_game
# ======================================================================

class TestPredictGame:

    def test_basic_prediction(self, predictor):
        result = _run(predictor.predict_game("Test University", "Opponent State"))
        assert 'error' not in result
        assert result['predicted_total'] > 0
        assert result['confidence'] > 0

    def test_stronger_team_favored(self, predictor):
        result = _run(predictor.predict_game("Test University", "Opponent State"))
        # Test U has better offense and pitching
        assert result['home_win_probability'] > 0.5
        assert result['predicted_winner'] == "Test University"

    def test_spread_analysis(self, predictor):
        result = _run(predictor.predict_game("Test University", "Opponent State",
                                               spread=-3.5))
        assert 'spread_pick' in result
        assert 'spread_edge' in result

    def test_over_under_analysis(self, predictor):
        result = _run(predictor.predict_game("Test University", "Opponent State",
                                               over_under=10.5))
        assert 'ou_pick' in result
        assert 'ou_edge' in result

    def test_missing_away_team(self, predictor):
        result = _run(predictor.predict_game("Test University", "Ghost Team"))
        assert result.get('error') == 'Insufficient data'

    def test_model_type_pythagorean(self, predictor):
        result = _run(predictor.predict_game("Test University", "Opponent State"))
        assert result['model'] == 'pythagorean'

    def test_win_probabilities_sum_to_one(self, predictor):
        result = _run(predictor.predict_game("Test University", "Opponent State"))
        total_prob = result['home_win_probability'] + result['away_win_probability']
        assert total_prob == pytest.approx(1.0, abs=0.01)
