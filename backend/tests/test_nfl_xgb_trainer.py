from datetime import date

from scripts.nfl_xgb_trainer import build_live_features, build_training_examples


def schedule_row(game_date, season, week, home, away, home_score, away_score, game_type="REG"):
    return {
        "season": season,
        "game_date": None,
        "home_score": None,
        "away_score": None,
        "metadata": {
            "gameday": game_date,
            "week": week,
            "game_type": game_type,
            "home_team": home,
            "away_team": away,
            "home_score": home_score,
            "away_score": away_score,
            "home_moneyline": -150,
            "away_moneyline": 130,
        },
    }


def weekly_row(season, week, team, **stats):
    return {
        "season": season,
        "metadata": {
            "season": season,
            "week": week,
            "team": team,
            **stats,
        },
    }


def history_rows():
    return [
        schedule_row("2024-09-01", 2024, 1, "KC", "BAL", 27, 20),
        schedule_row("2024-09-01", 2024, 1, "MIA", "BUF", 21, 24),
        schedule_row("2024-09-08", 2024, 2, "KC", "CIN", 24, 17),
        schedule_row("2024-09-08", 2024, 2, "MIA", "JAX", 31, 10),
        # Same-day completed games must not enter one another's pregame features.
        schedule_row("2024-09-15", 2024, 3, "KC", "MIA", 20, 17),
        schedule_row("2024-09-15", 2024, 3, "BUF", "SEA", 21, 14),
        schedule_row("2024-09-22", 2024, 4, "Kansas City Chiefs", "Miami Dolphins", None, None),
    ]


def test_training_features_use_only_games_before_target_date():
    rows = history_rows()
    features, labels, totals, game_dates, market_probabilities = build_training_examples(rows)

    # First eligible KC/MIA target is Sep 15, whose feature values use Sep 1 and Sep 8 only.
    target_index = game_dates.index(date(2024, 9, 15))
    target = features[target_index]
    assert target["home_ppg"] == 25.5
    assert target["away_ppg"] == 26.0
    assert labels[target_index] == 1
    assert totals[target_index] == 37
    assert market_probabilities[target_index] is not None


def test_live_features_match_training_builder_and_skip_current_week_stats():
    weekly = [
        weekly_row(2024, 1, "KC", pass_yds=200, rush_yds=80, pass_td=2, rush_td=1, pass_int=0),
        weekly_row(2024, 2, "KC", pass_yds=300, rush_yds=100, pass_td=1, rush_td=1, pass_int=1),
        weekly_row(2024, 3, "KC", pass_yds=999, rush_yds=999, pass_td=9, rush_td=9, pass_int=9),
        weekly_row(2024, 1, "MIA", pass_yds=180, rush_yds=110, pass_td=1, rush_td=1, pass_int=1),
        weekly_row(2024, 2, "MIA", pass_yds=220, rush_yds=90, pass_td=2, rush_td=0, pass_int=0),
    ]

    features = build_live_features(
        history_rows(), "Kansas City Chiefs", "Miami Dolphins", weekly, as_of=date(2024, 9, 14)
    )

    assert features["home_ppg"] == 25.5
    assert features["away_ppg"] == 26.0
    assert features["home_pass_yds_per_game"] == 250
    assert features["home_rush_yds_per_game"] == 90
    assert features["home_td_per_game"] == 2.5
    assert features["home_turnovers_per_game"] == 0.5
    assert features["home_pass_yds_per_game"] != 999
