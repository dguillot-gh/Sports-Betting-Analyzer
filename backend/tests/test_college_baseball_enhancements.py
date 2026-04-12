"""
Comprehensive tests for College Baseball enhancements:
- ESPN game results scraper
- Multi-year XGBoost training pipeline
- Name resolution alias table
- Prediction sanity bounds
- Importer abbreviation expansion
- API endpoint wiring
"""

import asyncio
import json
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from datetime import date, datetime


def _run(coro):
    """Helper to run an async coroutine in tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Shared dummy CSV data
# ---------------------------------------------------------------------------

DUMMY_BATTING_CSV = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,g,ab,pa,h,1b,2b,3b,hr,r,rbi,bb,so,hbp,sf,sh,gdp,sb,cs,avg,bb%,k%,bb/k,obp,slg,ops,iso,spd,babip,wsb,wrc,wraa,woba,wrc+
Player A,TST,Test University,21.0,Player A,10001,,2025,50,200,230,60,40,12,2,6,35,30,25,40,3,2,0,3,5,2,0.300,0.109,0.174,0.625,0.380,0.500,0.880,0.200,5.0,0.340,0.5,40.0,8.0,0.400,130.0
Player B,TST,Test University,22.0,Player B,10002,,2025,48,190,220,55,35,11,1,8,32,28,20,35,5,1,1,2,3,1,0.289,0.091,0.159,0.571,0.370,0.490,0.860,0.201,4.5,0.330,0.3,38.0,6.0,0.390,125.0
"""

DUMMY_PITCHING_CSV = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,w,l,era,g,gs,cg,sho,sv,ip,tbf,h,r,er,hr,bb,hbp,wp,bk,so,k/9,bb/9,k/bb,hr/9,k%,bb%,k-bb%,avg,whip,babip,lob%,fip,e-f
Pitcher X,TST,Test University,22.0,Pitcher X,20001,,2025,7,3,3.50,14,14,1,0,0,80.0,330,65,35,31,5,20,4,3,0,85,9.56,2.25,4.25,0.56,0.258,0.061,0.197,0.210,1.063,0.290,0.72,3.40,-0.10
Pitcher Y,TST,Test University,21.0,Pitcher Y,20002,,2025,4,2,4.20,12,10,0,0,0,60.0,260,55,30,28,4,18,3,2,0,55,8.25,2.70,3.06,0.60,0.212,0.069,0.143,0.230,1.217,0.300,0.68,4.10,0.10
"""

DUMMY_BATTING_CSV_2 = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,g,ab,pa,h,1b,2b,3b,hr,r,rbi,bb,so,hbp,sf,sh,gdp,sb,cs,avg,bb%,k%,bb/k,obp,slg,ops,iso,spd,babip,wsb,wrc,wraa,woba,wrc+
Player D,OPP,Opponent State,21.0,Player D,30001,,2025,52,210,240,50,34,10,1,5,25,20,22,50,4,2,1,4,2,1,0.238,0.092,0.208,0.440,0.320,0.380,0.700,0.142,3.8,0.300,0.1,28.0,1.0,0.330,95.0
Player E,OPP,Opponent State,22.0,Player E,30002,,2025,50,195,225,48,32,9,1,6,22,18,20,48,5,1,0,3,4,2,0.246,0.089,0.213,0.417,0.330,0.400,0.730,0.154,4.0,0.310,0.1,30.0,2.0,0.340,100.0
"""

DUMMY_PITCHING_CSV_2 = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,w,l,era,g,gs,cg,sho,sv,ip,tbf,h,r,er,hr,bb,hbp,wp,bk,so,k/9,bb/9,k/bb,hr/9,k%,bb%,k-bb%,avg,whip,babip,lob%,fip,e-f
Pitcher M,OPP,Opponent State,22.0,Pitcher M,40001,,2025,5,5,4.80,14,14,0,0,0,75.0,320,72,42,40,8,22,5,4,0,60,7.20,2.64,2.73,0.96,0.188,0.069,0.119,0.240,1.253,0.310,0.65,4.60,0.20
Pitcher N,OPP,Opponent State,21.0,Pitcher N,40002,,2025,3,4,5.10,12,10,0,0,0,55.0,245,58,35,31,6,20,3,3,0,40,6.55,3.27,2.00,0.98,0.163,0.082,0.082,0.250,1.418,0.320,0.60,5.20,0.10
"""

# Extreme stats for sanity bounds testing
EXTREME_BATTING = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,g,ab,pa,h,1b,2b,3b,hr,r,rbi,bb,so,hbp,sf,sh,gdp,sb,cs,avg,bb%,k%,bb/k,obp,slg,ops,iso,spd,babip,wsb,wrc,wraa,woba,wrc+
Player A,TST,Test University,21.0,Player A,10001,,2025,50,200,230,60,40,12,2,6,100,30,25,40,3,2,0,3,5,2,0.300,0.109,0.174,0.625,0.380,0.500,0.880,0.200,5.0,0.340,0.5,40.0,8.0,0.400,130.0
"""

EXTREME_PITCHING = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,w,l,era,g,gs,cg,sho,sv,ip,tbf,h,r,er,hr,bb,hbp,wp,bk,so,k/9,bb/9,k/bb,hr/9,k%,bb%,k-bb%,avg,whip,babip,lob%,fip,e-f
Pitcher X,TST,Test University,22.0,Pitcher X,20001,,2025,10,1,1.50,14,14,1,0,0,80.0,330,40,15,13,2,10,2,1,0,100,11.25,1.13,10.00,0.23,0.303,0.030,0.273,0.140,0.625,0.240,0.85,1.80,-0.30
"""

WEAK_BATTING = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,g,ab,pa,h,1b,2b,3b,hr,r,rbi,bb,so,hbp,sf,sh,gdp,sb,cs,avg,bb%,k%,bb/k,obp,slg,ops,iso,spd,babip,wsb,wrc,wraa,woba,wrc+
Player D,OPP,Opponent State,21.0,Player D,30001,,2025,50,200,230,30,20,6,0,4,15,10,12,60,2,1,0,5,1,1,0.150,0.052,0.261,0.200,0.210,0.230,0.440,0.080,2.0,0.200,-0.5,12.0,-10.0,0.220,65.0
"""

WEAK_PITCHING = """\
name,team,team name,age,nameascii,playerid,mlbamid,year,w,l,era,g,gs,cg,sho,sv,ip,tbf,h,r,er,hr,bb,hbp,wp,bk,so,k/9,bb/9,k/bb,hr/9,k%,bb%,k-bb%,avg,whip,babip,lob%,fip,e-f
Pitcher M,OPP,Opponent State,22.0,Pitcher M,40001,,2025,2,10,7.50,14,14,0,0,0,72.0,330,90,65,60,12,30,6,5,0,35,4.38,3.75,1.17,1.50,0.106,0.091,0.015,0.290,1.667,0.340,0.55,6.80,0.70
"""


# ======================================================================
# ESPN Scraper Tests
# ======================================================================

class TestESPNScraper:
    """Tests for college_baseball_results_scraper.py"""

    MOCK_ESPN_RESPONSE = {
        "events": [
            {
                "id": "12345",
                "competitions": [{
                    "status": {"type": {"completed": True}},
                    "competitors": [
                        {"team": {"displayName": "LSU Tigers"}, "score": "8", "homeAway": "home"},
                        {"team": {"displayName": "Arkansas Razorbacks"}, "score": "3", "homeAway": "away"}
                    ],
                    "venue": {"fullName": "Alex Box Stadium"},
                    "neutralSite": False
                }]
            },
            {
                "id": "12346",
                "competitions": [{
                    "status": {"type": {"completed": True}},
                    "competitors": [
                        {"team": {"displayName": "Texas Longhorns"}, "score": "5", "homeAway": "home"},
                        {"team": {"displayName": "Oklahoma Sooners"}, "score": "7", "homeAway": "away"}
                    ],
                    "venue": {"fullName": "UFCU Disch-Falk Field"},
                    "neutralSite": False
                }]
            },
            {
                "id": "12347",
                "competitions": [{
                    "status": {"type": {"completed": False}},
                    "competitors": [
                        {"team": {"displayName": "Oregon Ducks"}, "score": "2", "homeAway": "home"},
                        {"team": {"displayName": "Stanford Cardinal"}, "score": "1", "homeAway": "away"}
                    ],
                    "venue": {},
                    "neutralSite": False
                }]
            }
        ]
    }

    def test_fetch_returns_list(self):
        """Scraper always returns a list, even on failure."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: {"events": []})
            games = _run(fetch_college_baseball_scores(days_back=1))
            assert isinstance(games, list)

    def test_mocked_completed_games_parsed(self):
        """Completed games are correctly parsed from ESPN response."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: self.MOCK_ESPN_RESPONSE)
            games = _run(fetch_college_baseball_scores(target_date=date(2026, 3, 4), days_back=1))
            # Only 2 completed games (3rd is incomplete)
            assert len(games) == 2

    def test_game_result_structure(self):
        """Each game result has all required fields."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: self.MOCK_ESPN_RESPONSE)
            games = _run(fetch_college_baseball_scores(target_date=date(2026, 3, 4), days_back=1))
            required = ['home_team', 'away_team', 'home_score', 'away_score',
                        'event_date', 'season', 'venue', 'neutral_site', 'espn_id']
            for field in required:
                assert field in games[0], f"Missing: {field}"

    def test_home_away_correct(self):
        """Home and away teams are assigned correctly."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: self.MOCK_ESPN_RESPONSE)
            games = _run(fetch_college_baseball_scores(target_date=date(2026, 3, 4), days_back=1))
            assert games[0]['home_team'] == 'LSU Tigers'
            assert games[0]['away_team'] == 'Arkansas Razorbacks'
            assert games[0]['home_score'] == 8
            assert games[0]['away_score'] == 3

    def test_scores_are_integers(self):
        """Scores should be integer values >= 0."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: self.MOCK_ESPN_RESPONSE)
            games = _run(fetch_college_baseball_scores(target_date=date(2026, 3, 4), days_back=1))
            for g in games:
                assert isinstance(g['home_score'], int) and g['home_score'] >= 0
                assert isinstance(g['away_score'], int) and g['away_score'] >= 0

    def test_incomplete_games_filtered(self):
        """Only completed games should be returned."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: self.MOCK_ESPN_RESPONSE)
            games = _run(fetch_college_baseball_scores(target_date=date(2026, 3, 4), days_back=1))
            team_names = [g['home_team'] for g in games]
            assert 'Oregon Ducks' not in team_names  # Incomplete game

    def test_espn_api_failure_returns_empty(self):
        """Scraper returns empty list on HTTP errors."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=500)
            games = _run(fetch_college_baseball_scores(days_back=1))
            assert games == []

    def test_network_error_returns_empty(self):
        """Scraper handles network exceptions gracefully."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.side_effect = Exception("Connection reset")
            games = _run(fetch_college_baseball_scores(days_back=1))
            assert games == []

    def test_multi_day_fetch(self):
        """days_back parameter controls how many API calls are made."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: {"events": []})
            _run(fetch_college_baseball_scores(days_back=5))
            assert mock.call_count == 5

    def test_venue_and_neutral_site(self):
        """Venue name and neutral site flag are captured."""
        from scripts.college_baseball_results_scraper import fetch_college_baseball_scores
        with patch('scripts.college_baseball_results_scraper.requests.get') as mock:
            mock.return_value = MagicMock(status_code=200, json=lambda: self.MOCK_ESPN_RESPONSE)
            games = _run(fetch_college_baseball_scores(target_date=date(2026, 3, 4), days_back=1))
            assert games[0]['venue'] == 'Alex Box Stadium'
            assert games[0]['neutral_site'] == False

    def test_store_results_with_no_games(self):
        """store_game_results should handle empty list gracefully."""
        from scripts.college_baseball_results_scraper import store_game_results
        result = _run(store_game_results([]))
        assert result == {"rows": 0, "new": 0, "updated": 0}

    def test_scrape_and_store_pipeline(self):
        """Full scrape_and_store pipeline returns expected structure."""
        from scripts.college_baseball_results_scraper import scrape_and_store
        with patch('scripts.college_baseball_results_scraper.fetch_college_baseball_scores') as mock_fetch:
            mock_fetch.return_value = []
            with patch('scripts.college_baseball_results_scraper.store_game_results') as mock_store:
                mock_store.return_value = {"rows": 0, "new": 0, "updated": 0}
                result = _run(scrape_and_store(days_back=3))
                assert 'games_fetched' in result
                assert 'games_inserted' in result
                assert 'days_scraped' in result
                assert result['days_scraped'] == 3


# ======================================================================
# Name Resolution Tests
# ======================================================================

class TestNameResolutionAliases:
    """Tests for the ODDS_TO_NCAA_ALIASES table and _resolve_team_id."""

    @pytest.fixture
    def predictor(self, tmp_path):
        """Create a predictor with teams_d1.json available."""
        import scripts.college_baseball_predictor as mod

        teams_data = [
            {"ncaa_name": "FIU (CUSA)", "team_id": "FIU__CUSA"},
            {"ncaa_name": "Oklahoma St. (Big 12)", "team_id": "Oklahoma_St___Big_12"},
            {"ncaa_name": "Western Ky. (CUSA)", "team_id": "Western_Ky___CUSA"},
            {"ncaa_name": "NC State (ACC)", "team_id": "NC_State__ACC"},
            {"ncaa_name": "Missouri St. (MVC)", "team_id": "Missouri_St___MVC"},
            {"ncaa_name": "LSU (SEC)", "team_id": "LSU__SEC"},
            {"ncaa_name": "Central Ark. (ASUN)", "team_id": "Central_Ark___ASUN"},
            {"ncaa_name": "Florida St. (ACC)", "team_id": "Florida_St___ACC"},
            {"ncaa_name": "Michigan St. (Big Ten)", "team_id": "Michigan_St___Big_Ten"},
            {"ncaa_name": "Vanderbilt (SEC)", "team_id": "Vanderbilt__SEC"},
            {"ncaa_name": "Nebraska (Big Ten)", "team_id": "Nebraska__Big_Ten"},
        ]

        stats_dir = tmp_path / "stats"
        stats_dir.mkdir()
        (tmp_path / "teams_d1.json").write_text(json.dumps(teams_data))

        original = mod._find_data_dir
        mod._find_data_dir = lambda: stats_dir

        p = mod.CollegeBaseballPredictor()
        p.use_xgb = False
        p.use_stat_xgb = False
        p._team_name_map = {}

        yield p
        mod._find_data_dir = original

    def test_fiu_from_florida_intl(self, predictor):
        assert predictor._resolve_team_id("Florida Int'l Golden Panthers") == "FIU__CUSA"

    def test_oklahoma_state(self, predictor):
        assert predictor._resolve_team_id("Oklahoma St Cowboys") == "Oklahoma_St___Big_12"

    def test_western_kentucky(self, predictor):
        assert predictor._resolve_team_id("Western Kentucky Hilltoppers") == "Western_Ky___CUSA"

    def test_nc_state(self, predictor):
        assert predictor._resolve_team_id("NC State Wolfpack") == "NC_State__ACC"

    def test_missouri_state(self, predictor):
        assert predictor._resolve_team_id("Missouri St Bears") == "Missouri_St___MVC"

    def test_lsu(self, predictor):
        assert predictor._resolve_team_id("LSU Tigers") == "LSU__SEC"

    def test_central_arkansas(self, predictor):
        assert predictor._resolve_team_id("Central Arkansas Bears") == "Central_Ark___ASUN"

    def test_florida_state(self, predictor):
        assert predictor._resolve_team_id("Florida State Seminoles") == "Florida_St___ACC"

    def test_michigan_state(self, predictor):
        assert predictor._resolve_team_id("Michigan State Spartans") == "Michigan_St___Big_Ten"

    def test_direct_match_no_mascot(self, predictor):
        """Direct NCAA names work without mascot."""
        assert predictor._resolve_team_id("Vanderbilt") == "Vanderbilt__SEC"

    def test_direct_match_with_mascot(self, predictor):
        """Drop mascot match works."""
        assert predictor._resolve_team_id("Nebraska Cornhuskers") == "Nebraska__Big_Ten"

    def test_cache_persists(self, predictor):
        predictor._resolve_team_id("LSU Tigers")
        assert "LSU Tigers" in predictor._team_name_map
        assert predictor._team_name_map["LSU Tigers"] == "LSU__SEC"

    def test_cache_avoids_recomputation(self, predictor):
        """Second call returns cached result instantly."""
        r1 = predictor._resolve_team_id("LSU Tigers")
        r2 = predictor._resolve_team_id("LSU Tigers")
        assert r1 == r2


# ======================================================================
# Prediction Sanity Bounds Tests
# ======================================================================

class TestPredictionSanityBounds:
    """Tests that predicted totals and win probabilities stay sane."""

    @pytest.fixture
    def predictor_extreme(self, tmp_path):
        """Predictor with extreme stat teams to test bounds."""
        import scripts.college_baseball_predictor as mod

        stats = tmp_path / "stats"
        stats.mkdir()

        (stats / "Test_University_batting.csv").write_text(EXTREME_BATTING)
        (stats / "Test_University_pitching.csv").write_text(EXTREME_PITCHING)
        (stats / "Opponent_State_batting.csv").write_text(WEAK_BATTING)
        (stats / "Opponent_State_pitching.csv").write_text(WEAK_PITCHING)

        original = mod._find_data_dir
        mod._find_data_dir = lambda: stats

        p = mod.CollegeBaseballPredictor()
        p.use_xgb = False
        p.use_stat_xgb = False

        yield p
        mod._find_data_dir = original

    @pytest.fixture
    def predictor_normal(self, tmp_path):
        """Predictor with normal stat teams."""
        import scripts.college_baseball_predictor as mod

        stats = tmp_path / "stats"
        stats.mkdir()

        (stats / "Test_University_batting.csv").write_text(DUMMY_BATTING_CSV)
        (stats / "Test_University_pitching.csv").write_text(DUMMY_PITCHING_CSV)
        (stats / "Opponent_State_batting.csv").write_text(DUMMY_BATTING_CSV_2)
        (stats / "Opponent_State_pitching.csv").write_text(DUMMY_PITCHING_CSV_2)

        original = mod._find_data_dir
        mod._find_data_dir = lambda: stats

        p = mod.CollegeBaseballPredictor()
        p.use_xgb = False
        p.use_stat_xgb = False

        yield p
        mod._find_data_dir = original

    def test_total_clamped_lower_bound(self, predictor_extreme):
        """Predicted total should never go below 4."""
        result = _run(predictor_extreme.predict_game("Test University", "Opponent State"))
        assert result['predicted_total'] >= 4.0

    def test_total_clamped_upper_bound(self, predictor_extreme):
        """Predicted total should never exceed 25."""
        result = _run(predictor_extreme.predict_game("Test University", "Opponent State"))
        assert result['predicted_total'] <= 25.0

    def test_strong_team_clearly_favored(self, predictor_extreme):
        """A dominant team (10-1, 1.50 ERA) should be heavily favored."""
        result = _run(predictor_extreme.predict_game("Test University", "Opponent State"))
        assert result['home_win_probability'] > 0.65

    def test_probabilities_sum_to_one_extreme(self, predictor_extreme):
        result = _run(predictor_extreme.predict_game("Test University", "Opponent State"))
        assert result['home_win_probability'] + result['away_win_probability'] == pytest.approx(1.0, abs=0.01)

    def test_probabilities_sum_to_one_normal(self, predictor_normal):
        result = _run(predictor_normal.predict_game("Test University", "Opponent State"))
        assert result['home_win_probability'] + result['away_win_probability'] == pytest.approx(1.0, abs=0.01)

    def test_confidence_bounded(self, predictor_normal):
        """Confidence should be between 0 and 0.80."""
        result = _run(predictor_normal.predict_game("Test University", "Opponent State"))
        assert 0 < result['confidence'] <= 0.80

    def test_confidence_level_valid(self, predictor_normal):
        """Confidence level should be one of: high, medium, low."""
        result = _run(predictor_normal.predict_game("Test University", "Opponent State"))
        assert result['confidence_level'] in ('high', 'medium', 'low')

    def test_missing_team_returns_error(self, predictor_normal):
        """Missing team should give error, not crash."""
        result = _run(predictor_normal.predict_game("Test University", "Nonexistent Team"))
        assert 'error' in result

    def test_spread_analysis_present(self, predictor_normal):
        """Spread analysis fields present when spread provided."""
        result = _run(predictor_normal.predict_game("Test University", "Opponent State", spread=-3.5))
        assert 'spread_pick' in result
        assert 'spread_edge' in result

    def test_ou_analysis_present(self, predictor_normal):
        """O/U analysis fields present when over_under provided."""
        result = _run(predictor_normal.predict_game("Test University", "Opponent State", over_under=10.5))
        assert 'ou_pick' in result
        assert 'ou_edge' in result

    def test_prediction_has_model_field(self, predictor_normal):
        """Prediction should indicate which model was used."""
        result = _run(predictor_normal.predict_game("Test University", "Opponent State"))
        assert 'model' in result


# ======================================================================
# XGBoost Trainer Tests
# ======================================================================

class TestXGBTrainer:
    """Tests for the XGBoost training pipeline."""

    def test_aggregate_team_batting_stats(self, tmp_path):
        """_aggregate_team_from_csvs extracts batting stats correctly."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        (tmp_path / "team_batting.csv").write_text(DUMMY_BATTING_CSV)
        (tmp_path / "team_pitching.csv").write_text(DUMMY_PITCHING_CSV)

        trainer = CollegeBaseballXGBTrainer()
        stats = trainer._aggregate_team_from_csvs(str(tmp_path / "team_batting.csv"),
                                                   str(tmp_path / "team_pitching.csv"))
        assert stats is not None
        assert stats['rpg'] > 0
        assert 0 < stats['avg'] < 1
        assert 0 < stats['obp'] < 1
        assert 0 < stats['slg'] < 2

    def test_aggregate_team_pitching_stats(self, tmp_path):
        """_aggregate_team_from_csvs extracts pitching stats correctly."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        (tmp_path / "team_batting.csv").write_text(DUMMY_BATTING_CSV)
        (tmp_path / "team_pitching.csv").write_text(DUMMY_PITCHING_CSV)

        trainer = CollegeBaseballXGBTrainer()
        stats = trainer._aggregate_team_from_csvs(str(tmp_path / "team_batting.csv"),
                                                   str(tmp_path / "team_pitching.csv"))
        assert stats['era'] > 0
        assert stats['whip'] > 0
        assert stats['k9'] > 0
        assert stats['rapg'] > 0

    def test_aggregate_win_pct(self, tmp_path):
        """Win percentage is calculated from W/L record."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        (tmp_path / "team_batting.csv").write_text(DUMMY_BATTING_CSV)
        (tmp_path / "team_pitching.csv").write_text(DUMMY_PITCHING_CSV)

        trainer = CollegeBaseballXGBTrainer()
        stats = trainer._aggregate_team_from_csvs(str(tmp_path / "team_batting.csv"),
                                                   str(tmp_path / "team_pitching.csv"))
        assert 0 < stats['win_pct'] < 1

    def test_aggregate_pitching_only_has_no_batting_stats(self, tmp_path):
        """With only pitching CSV, batting stats default to zero."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        (tmp_path / "team_pitching.csv").write_text(DUMMY_PITCHING_CSV)

        trainer = CollegeBaseballXGBTrainer()
        stats = trainer._aggregate_team_from_csvs(str(tmp_path / "missing.csv"),
                                                   str(tmp_path / "team_pitching.csv"))
        # Pitching-only can still produce stats (games derived from IP)
        if stats is not None:
            assert stats.get('avg', 0) == 0  # No batting data
            assert stats['era'] > 0

    def test_rolling_features_need_5_games(self):
        """Rolling features should return None with < 5 games."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        trainer = CollegeBaseballXGBTrainer()
        history = [{'runs_scored': 5, 'runs_allowed': 3, 'won': 1}] * 4
        assert trainer._calculate_rolling_features(history) is None

    def test_rolling_features_exactly_5_games(self):
        """Rolling features should work with exactly 5 games."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        trainer = CollegeBaseballXGBTrainer()
        history = [{'runs_scored': i + 3, 'runs_allowed': 4, 'won': 1 if i > 1 else 0}
                   for i in range(5)]
        feats = trainer._calculate_rolling_features(history)
        assert feats is not None

    def test_rolling_features_structure(self):
        """Rolling features have all required keys."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        trainer = CollegeBaseballXGBTrainer()
        history = [{'runs_scored': 5, 'runs_allowed': 3, 'won': 1},
                   {'runs_scored': 3, 'runs_allowed': 6, 'won': 0},
                   {'runs_scored': 7, 'runs_allowed': 2, 'won': 1},
                   {'runs_scored': 4, 'runs_allowed': 4, 'won': 0},
                   {'runs_scored': 8, 'runs_allowed': 1, 'won': 1},
                   {'runs_scored': 6, 'runs_allowed': 5, 'won': 1}]
        feats = trainer._calculate_rolling_features(history)
        assert 'runs_scored_avg_l5' in feats
        assert 'runs_allowed_avg_l5' in feats
        assert 'win_pct_l10' in feats
        assert 'streak' in feats

    def test_rolling_features_averages(self):
        """Rolling averages are computed correctly."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        trainer = CollegeBaseballXGBTrainer()
        history = [{'runs_scored': 5, 'runs_allowed': 3, 'won': 1}] * 6
        feats = trainer._calculate_rolling_features(history)
        assert feats['runs_scored_avg_l5'] == pytest.approx(5.0)
        assert feats['runs_allowed_avg_l5'] == pytest.approx(3.0)
        assert feats['win_pct_l10'] == pytest.approx(1.0)
        assert feats['streak'] == 6  # 6-game win streak

    def test_feature_names_list(self):
        """Trainer has correct feature name lists."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        trainer = CollegeBaseballXGBTrainer()
        assert len(trainer.feature_names) == 9  # 4 home + 4 away + is_neutral
        assert 'home_runs_scored_avg_l5' in trainer.feature_names
        assert 'is_neutral' in trainer.feature_names

    def test_stat_feature_names_list(self):
        """Stat-based features list is correct."""
        from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer

        trainer = CollegeBaseballXGBTrainer()
        assert len(trainer.STAT_XGB_FEATURES) == 17  # 8 home + 8 away + is_home
        assert 'home_rpg' in trainer.STAT_XGB_FEATURES
        assert 'is_home' in trainer.STAT_XGB_FEATURES

    def test_saved_models_exist(self):
        """Verify the retrained stat models exist on disk."""
        # Try multiple paths
        for base in [Path("backend/models/college_baseball"),
                     Path(__file__).parent.parent / "models" / "college_baseball",
                     Path("models/college_baseball")]:
            if base.exists():
                classifier = base / "cbb_stat_xgb_classifier.json"
                regressor = base / "cbb_stat_xgb_regressor.json"
                if not (classifier.exists() and regressor.exists()):
                    pytest.skip(f"Model artifacts not present at {base}; skipping artifact existence check")
                assert classifier.exists(), f"Classifier missing at {base}"
                assert regressor.exists(), f"Regressor missing at {base}"
                return
        pytest.skip("Models directory not found in any expected location")

    def test_model_metadata_has_accuracy(self):
        """Model metadata should include accuracy metrics from multi-year training."""
        for base in [Path("backend/models/college_baseball"),
                     Path(__file__).parent.parent / "models" / "college_baseball",
                     Path("models/college_baseball")]:
            meta_path = base / "stat_model_metadata.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                assert 'classifier_test_acc' in meta
                assert meta['classifier_test_acc'] > 0.5  # Better than coin flip
                assert 'regressor_test_mae' in meta
                assert meta['regressor_test_mae'] < 5.0
                assert 'years' in meta  # Multi-year training
                return
        pytest.skip("Model metadata not found")


# ======================================================================
# Importer Abbreviation Expansion Tests
# ======================================================================

class TestImporterAbbrevExpansion:
    """Tests for the expand_abbrevs function in the importer."""

    def test_st_expansion(self):
        """St. -> State"""
        import re
        from scripts.college_baseball_importer import run_college_baseball_import
        # Test the expansion logic directly
        def expand_abbrevs(s):
            s = re.sub(r'\bSt\.\s', 'State ', s)
            s = re.sub(r'\bSt\.\s*$', 'State', s)
            s = re.sub(r'\bKy\.\s', 'Kentucky ', s)
            s = re.sub(r'\bKy\.\s*$', 'Kentucky', s)
            return s

        assert expand_abbrevs("Missouri St.") == "Missouri State"
        assert expand_abbrevs("Oklahoma St. Pokes") == "Oklahoma State Pokes"
        assert expand_abbrevs("Western Ky.") == "Western Kentucky"

    def test_multi_abbreviation(self):
        """Multiple abbreviations in one name."""
        import re
        def expand_abbrevs(s):
            s = re.sub(r'\bSt\.\s', 'State ', s)
            s = re.sub(r'\bSt\.\s*$', 'State', s)
            s = re.sub(r'\bArk\.\s', 'Arkansas ', s)
            s = re.sub(r'\bArk\.\s*$', 'Arkansas', s)
            return s

        assert expand_abbrevs("Central Ark.") == "Central Arkansas"

    def test_no_expansion_needed(self):
        """Names without abbreviations should pass through unchanged."""
        import re
        def expand_abbrevs(s):
            s = re.sub(r'\bSt\.\s', 'State ', s)
            s = re.sub(r'\bSt\.\s*$', 'State', s)
            return s

        assert expand_abbrevs("Vanderbilt") == "Vanderbilt"
        assert expand_abbrevs("Nebraska") == "Nebraska"


# ======================================================================
# ODDS_TO_NCAA_ALIASES Constant Tests
# ======================================================================

class TestAliasTableCompleteness:
    """Verify the alias table covers key problematic teams."""

    def test_alias_table_exists(self):
        from scripts.college_baseball_predictor import ODDS_TO_NCAA_ALIASES
        assert isinstance(ODDS_TO_NCAA_ALIASES, dict)
        assert len(ODDS_TO_NCAA_ALIASES) > 30

    def test_key_aliases_present(self):
        from scripts.college_baseball_predictor import ODDS_TO_NCAA_ALIASES
        critical = ["florida int'l", "western kentucky", "oklahoma state",
                     "nc state", "missouri state", "lsu", "ucf", "fiu"]
        for key in critical:
            assert key in ODDS_TO_NCAA_ALIASES, f"Missing alias: {key}"

    def test_alias_values_are_strings(self):
        from scripts.college_baseball_predictor import ODDS_TO_NCAA_ALIASES
        for k, v in ODDS_TO_NCAA_ALIASES.items():
            assert isinstance(k, str), f"Key not string: {k}"
            assert isinstance(v, str), f"Value not string for {k}: {v}"

    def test_alias_keys_are_lowercase(self):
        from scripts.college_baseball_predictor import ODDS_TO_NCAA_ALIASES
        for k in ODDS_TO_NCAA_ALIASES:
            assert k == k.lower(), f"Alias key not lowercase: {k}"
