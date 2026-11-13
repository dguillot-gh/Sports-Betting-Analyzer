"""Tests for the sport-name <-> import-log-job-name mapping used by /admin/data-freshness.

Regression context: MLB imports ran daily under job names mlb_results/mlb_stats/
mlb_training while the sports table says "mlb", so the freshness endpoint
reported "never" for a sport that was importing every night.
"""
from services.freshness_mapping import (
    build_import_map,
    job_names_for_sport,
    pick_best_import,
    sport_for_job,
)


def _log(sport, start_time, new_rows, rows, status="SUCCESS"):
    return {
        "sport": sport,
        "status": status,
        "start_time": start_time,
        "new_rows_imported": new_rows,
        "rows_imported": rows,
    }


def test_mlb_Uses_Its_Refresh_Job_Not_A_No_Op_Job():
    logs = [
        _log("mlb_training", "2026-11-09T09:08:56Z", 0, 0),
        _log("mlb_stats", "2026-11-09T09:08:00Z", 0, 565),
        _log("mlb_results", "2026-11-09T09:07:44Z", 7426, 7426),
    ]
    best = pick_best_import("mlb", logs)
    assert best is not None
    # The job that brought in new data wins over later no-op jobs.
    assert best["sport"] == "mlb_results"
    assert best["new_rows_imported"] == 7426


def test_nba_Falls_Back_To_Large_Refresh_When_No_New_Rows():
    logs = [
        _log("nba", "2026-11-08T09:00:00Z", 0, 0),
        _log("nba", "2026-11-09T09:00:00Z", 0, 105211),
        _log("nba_backtest", "2026-11-09T09:02:00Z", 162, 256),
    ]
    best = pick_best_import("nba", logs)
    assert best is not None
    assert best["new_rows_imported"] == 162  # most new rows wins
    assert best["sport"] == "nba_backtest"


def test_nascar_Includes_Supplemental_Job():
    logs = [
        _log("nascar", "2026-11-09T09:03:00Z", 0, 52386),
        _log("nascar_supplemental", "2026-11-09T09:05:00Z", 40, 3499),
    ]
    best = pick_best_import("nascar", logs)
    assert best is not None
    assert best["sport"] == "nascar_supplemental"
    assert best["new_rows_imported"] == 40


def test_Failed_Logs_Are_Ignored():
    logs = [
        _log("nfl", "2026-11-09T09:02:00Z", 0, 0, status="FAILED"),
        _log("nfl_training", "2026-11-09T09:03:00Z", 0, 1705),
    ]
    best = pick_best_import("nfl", logs)
    assert best is not None
    assert best["sport"] == "nfl_training"


def test_Unknown_Sport_Falls_Back_To_Exact_Name():
    logs = [_log("some_new_sport", "2026-11-09T09:00:00Z", 5, 5)]
    best = pick_best_import("some_new_sport", logs)
    assert best is not None
    assert best["sport"] == "some_new_sport"


def test_No_Matching_Log_Returns_None():
    assert pick_best_import("nhl", [_log("nba", "2026-11-09T09:00:00Z", 5, 5)]) is None
    assert pick_best_import("nhl", []) is None


def test_Ties_Break_To_Most_Recent_Then_Input_Order():
    a = _log("mlb_results", "2026-11-08T09:07:44Z", 7426, 7426)
    b = _log("mlb_results", "2026-11-09T09:07:44Z", 7426, 7426)
    assert pick_best_import("mlb", [a, b]) is b


def test_Sport_For_Job_And_Back():
    assert sport_for_job("mlb_results") == "mlb"
    assert sport_for_job("ncaab") == "ncaab"
    assert sport_for_job("unknown_job") is None
    assert sport_for_job(None) is None
    assert "mlb_results" in job_names_for_sport("mlb")
    assert job_names_for_sport("unknown") == ["unknown"]


def test_Build_Import_Map_Covers_All_Listed_Sports():
    logs = [
        _log("mlb_results", "2026-11-09T09:07:44Z", 7426, 7426),
        _log("cfb", "2026-11-09T09:07:00Z", 29779, 29779),
        _log("ncaab", "2026-11-09T09:00:00Z", 53207, 53207),
    ]
    mapping = build_import_map(["mlb", "college_football", "ncaab", "nhl"], logs)
    assert set(mapping.keys()) == {"mlb", "college_football", "ncaab", "nhl"}
    assert mapping["mlb"]["sport"] == "mlb_results"
    assert mapping["college_football"]["sport"] == "cfb"
    assert mapping["ncaab"]["sport"] == "ncaab"
    assert mapping["nhl"] is None
