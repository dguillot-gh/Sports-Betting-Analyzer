"""Unit tests for pure helpers in services.clv_calculator (no DB calls)."""
import pytest

from services.clv_calculator import CLVCalculator


@pytest.fixture
def calc():
    return CLVCalculator(db_url="postgresql://unused")


class TestCalculateClv:
    def test_improvement_positive(self, calc):
        # Placed +100 (50%), closing -110 (52.38%) -> +4.76%
        assert calc.calculate_clv(+100, -110) == 4.76

    def test_decline_negative(self, calc):
        # Placed -110 (52.38%), closing +100 (50%) -> -4.55%
        assert calc.calculate_clv(-110, +100) == -4.55

    def test_same_odds_zero(self, calc):
        assert calc.calculate_clv(-110, -110) == 0.0

    def test_longshot_to_favorite_large_positive(self, calc):
        # +300 = 25% -> -300 = 75% => CLV = +200%
        assert calc.calculate_clv(+300, -300) == 200.0

    def test_rounding(self, calc):
        # +105 -> 48.78%, -105 -> 51.22% => CLV +5.0 (rounded to 2dp)
        assert calc.calculate_clv(+105, -105) == 5.0
        val = calc.calculate_clv(+100, -105)
        assert round(val, 2) == val


@pytest.fixture
def bet():
    return {
        "description": "Celtics to beat Bucks",
        "game_name": "Celtics at Bucks",
        "team1": "Celtics",
        "team2": "Bucks",
        "odds": -115,
    }


class TestExtractRelevantOdds:
    def test_home_side_by_team1(self, calc, bet):
        book = {"home_moneyline": -150, "away_moneyline": +130}
        # description contains 'celtics' (team1) -> home moneyline
        assert calc._extract_relevant_odds(bet, book) == -150

    def test_away_side_by_team2(self, calc, bet):
        bet["description"] = "Bucks to cover"
        book = {"home_moneyline": -150, "away_moneyline": +130}
        assert calc._extract_relevant_odds(bet, book) == +130

    def test_explicit_home_keyword(self, calc, bet):
        bet["description"] = "home team to win"
        book = {"home_moneyline": -120, "away_moneyline": +110}
        assert calc._extract_relevant_odds(bet, book) == -120

    def test_spread_fallback(self, calc, bet):
        book = {"spread": -3.5, "spread_odds": -110}
        assert calc._extract_relevant_odds(bet, book) == -110

    def test_no_matchable_odds_returns_none(self, calc, bet):
        book = {"over_under": 215}
        assert calc._extract_relevant_odds(bet, book) is None
