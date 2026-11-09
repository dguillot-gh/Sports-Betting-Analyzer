"""Unit tests for the pure heuristic in services.bet_grader.BetGrader.determine_outcome."""
import pytest

from services.bet_grader import BetGrader


@pytest.fixture
def grader():
    return BetGrader(db_url="postgresql://unused")


class TestNhlMoneyPuck:
    def test_win_when_goals_for_higher(self, grader):
        bet = {"description": "Bruins ML", "game_name": "Bruins at Maple Leafs"}
        meta = {"goalsfor": 5, "goalsagainst": 2, "team": "Bruins"}
        assert grader.determine_outcome(bet, meta) == "win"

    def test_loss_when_goals_against_higher(self, grader):
        bet = {"description": "Bruins ML", "game_name": "Bruins at Maple Leafs"}
        meta = {"goalsfor": 1, "goalsagainst": 3, "team": "Bruins"}
        assert grader.determine_outcome(bet, meta) == "loss"

    def test_tie_stays_pending(self, grader):
        bet = {"description": "Bruins ML", "game_name": "Bruins at Maple Leafs"}
        meta = {"goalsfor": 2, "goalsagainst": 2, "team": "Bruins"}
        assert grader.determine_outcome(bet, meta) == "pending"

    def test_wrong_team_not_graded(self, grader):
        bet = {"description": "Maple Leafs ML", "game_name": "Maple Leafs at Bruins"}
        meta = {"goalsfor": 5, "goalsagainst": 2, "team": "Bruins"}  # result is about Bruins
        # Bet is on the Leafs, but the result row is the Bruins' - must NOT be graded a win
        assert grader.determine_outcome(bet, meta) == "pending"


class TestNba:
    def test_win(self, grader):
        bet = {"description": "Nuggets ML", "game_name": "Nuggets at Suns"}
        meta = {"pts": 110, "opponent_pts": 98, "team": "Nuggets"}
        assert grader.determine_outcome(bet, meta) == "win"

    def test_loss(self, grader):
        bet = {"description": "Nuggets ML", "game_name": "Nuggets at Suns"}
        meta = {"pts": 98, "opponent_pts": 110, "team": "Nuggets"}
        assert grader.determine_outcome(bet, meta) == "loss"


class TestWinnerField:
    def test_winner_match_is_win(self, grader):
        bet = {"description": "Lakers", "game_name": "Lakers at Clippers"}
        meta = {"winner": "Lakers"}
        assert grader.determine_outcome(bet, meta) == "win"

    def test_case_insensitive(self, grader):
        bet = {"description": "lakers ml", "game_name": ""}
        meta = {"winner": "LAKERS"}
        assert grader.determine_outcome(bet, meta) == "win"


class TestFallbacks:
    def test_empty_metadata_pending(self, grader):
        bet = {"description": "anything", "game_name": ""}
        assert grader.determine_outcome(bet, {}) == "pending"

    def test_none_descriptions_handled(self, grader):
        bet = {"description": None, "game_name": None}
        meta = {"winner": "Nobody"}
        assert grader.determine_outcome(bet, meta) == "pending"

    def test_missing_winner_no_crash(self, grader):
        bet = {"description": "team", "game_name": "A at B"}
        assert grader.determine_outcome(bet, {"other": 1}) == "pending"
