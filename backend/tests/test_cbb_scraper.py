"""Regression tests for the CBB ESPN scoreboard parser.

Context: the nightly CBB results job imported 0 rows for weeks at a stretch.
The cause during the off-season is legitimate (no completed games), but the
parser previously had no test at all — if ESPN changed its payload shape the
pipeline would silently import 0 games for the WHOLE season with every log
still reading SUCCESS.
"""
from datetime import date

from scripts.college_baseball_results_scraper import extract_completed_games

GAME_DATE = date(2026, 3, 14)

EVENT_COMPLETED = {
    "id": "401722221",
    "competitions": [{
        "status": {"type": {"completed": True, "display_name": "Final"}},
        "competitors": [
            {"homeAway": "home", "team": {"displayName": "Duke Blue Devils"}, "score": "9"},
            {"homeAway": "away", "team": {"displayName": "NC State Wolfpack"}, "score": "7"},
        ],
        "venue": {"fullName": "Duke Field"},
        "neutralSite": False,
    }],
}

EVENT_IN_PROGRESS = {
    "id": "401722222",
    "competitions": [{
        "status": {"type": {"completed": False, "display_name": "2nd"}},
        "competitors": [
            {"homeAway": "home", "team": {"displayName": "Florida Gators"}, "score": "3"},
            {"homeAway": "away", "team": {"displayName": "LSU Tigers"}, "score": "2"},
        ],
    }],
}


def test_Completed_Game_Is_Parsed():
    games = extract_completed_games([EVENT_COMPLETED], GAME_DATE)
    assert len(games) == 1
    g = games[0]
    assert g["home_team"] == "Duke Blue Devils"
    assert g["away_team"] == "NC State Wolfpack"
    assert g["home_score"] == 9
    assert g["away_score"] == 7
    assert g["event_date"] == "2026-03-14"
    assert g["season"] == 2026
    assert g["espn_id"] == "401722221"
    assert g["venue"] == "Duke Field"


def test_Incomplete_Games_Are_Skipped():
    games = extract_completed_games([EVENT_COMPLETED, EVENT_IN_PROGRESS], GAME_DATE)
    assert len(games) == 1
    assert games[0]["espn_id"] == "401722221"


def test_Malformed_Events_Are_Skipped_Not_Fatal():
    events = [
        {"id": 1},                                          # no competitions
        {"id": 2, "competitions": []},                      # empty competitions
        {"id": 3, "competitions": [{"status": {"type": {}}, "competitors": []}]},  # 0 competitors
        {  # missing away team
            "id": 4,
            "competitions": [{
                "status": {"type": {"completed": True}},
                "competitors": [{"homeAway": "home", "team": {"displayName": "X"}, "score": "1"}],
            }],
        },
        EVENT_COMPLETED,
    ]
    games = extract_completed_games(events, GAME_DATE)
    assert [g["espn_id"] for g in games] == ["401722221"]


def test_Garbage_Scoring_Treated_As_Zero():
    event = {
        "id": 99,
        "competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "H"}, "score": "abc"},
                {"homeAway": "away", "team": {"displayName": "A"}, "score": None},
            ],
        }],
    }
    games = extract_completed_games([event], GAME_DATE)
    assert games == [
        {
            "event_date": "2026-03-14",
            "season": 2026,
            "home_team": "H",
            "away_team": "A",
            "home_score": 0,
            "away_score": 0,
            "venue": "",
            "neutral_site": False,
            "espn_id": 99,
        }
    ]


def test_Empty_List():
    assert extract_completed_games([], GAME_DATE) == []
