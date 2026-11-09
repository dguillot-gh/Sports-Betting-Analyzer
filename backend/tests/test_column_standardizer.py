"""Unit tests for src.column_standardizer.ColumnStandardizer."""
import pandas as pd

from column_standardizer import ColumnStandardizer

SAMPLE_CONFIG = """
common:
  date: [date, game_date, GAME_DATE]
  season: [year, season]
nba:
  player: [player, name, PLAYER_NAME]
  points: [pts, POINTS]
  assists: [ast, AST]
nfl:
  passing_yards: [pass_yds, PassYds]
  team: [posteam, TEAM]
"""


def make_standardizer(tmp_path, config_text=SAMPLE_CONFIG):
    path = tmp_path / "column_aliases.yaml"
    path.write_text(config_text)
    return ColumnStandardizer(config_path=path)


class TestLoadConfig:
    def test_missing_config_returns_empty(self, tmp_path):
        std = ColumnStandardizer(config_path=tmp_path / "nope.yaml")
        assert std.aliases == {}

    def test_invalid_yaml_returns_empty(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(":\n\t - [broken")
        assert ColumnStandardizer(config_path=path).aliases == {}


class TestAliasMap:
    def test_sport_specific_and_common_merged(self, tmp_path):
        std = make_standardizer(tmp_path)
        m = std._get_alias_map("nba")
        assert m["pts"] == "points"
        assert m["game_date"] == "date"  # from common section

    def test_sport_specific_wins_over_common(self, tmp_path):
        cfg = SAMPLE_CONFIG + """
common:
  points: [scoring_pts]
"""
        std = make_standardizer(tmp_path, cfg)
        m = std._get_alias_map("nba")
        # 'scoring_pts' maps to 'points' (common), 'pts' still sport-specific
        assert m["scoring_pts"] == "points"
        assert m["pts"] == "points"

    def test_unknown_sport_falls_back_to_common(self, tmp_path):
        std = make_standardizer(tmp_path)
        m = std._get_alias_map("nascar")
        assert m["game_date"] == "date"
        assert "pts" not in m  # nba-only alias


class TestScan:
    def test_scan_reports_mapped_and_unmapped(self, tmp_path):
        std = make_standardizer(tmp_path)
        df = pd.DataFrame(columns=["PLAYER_NAME", "pts", "mystery_col"])
        report = std.scan(df, "nba")
        assert report.total_columns == 3
        assert report.mapped.get("PLAYER_NAME") == "player"
        # 'pts' is an alias of 'points', so it must be mapped, not unmapped
        assert report.mapped.get("pts") == "points"
        assert report.unmapped == ["mystery_col"]

    def test_scan_does_not_mutate_df(self, tmp_path):
        std = make_standardizer(tmp_path)
        df = pd.DataFrame({"PTS": [1], "player": ["a"]})
        std.scan(df, "nba")
        assert list(df.columns) == ["PTS", "player"]

    def test_report_to_dict_counts(self, tmp_path):
        std = make_standardizer(tmp_path)
        report = std.scan(pd.DataFrame(columns=["pts", "xyz"]), "nba")
        d = report.to_dict()
        assert d["mapped_count"] == 1
        assert d["unmapped_count"] == 1


class TestSuggest:
    def test_close_match_suggested(self, tmp_path):
        std = make_standardizer(tmp_path)
        # 'assists_count' contains alias 'ast'? No – but 'ast' is substring of ... use substring rule
        report = std.scan(pd.DataFrame(columns=["ast_old"]), "nba")
        assert "ast_old" in report.unmapped
        assert report.suggestions.get("ast_old") == "assists"


class TestStandardize:
    def test_renames_columns(self, tmp_path):
        std = make_standardizer(tmp_path)
        df = pd.DataFrame({"PLAYER_NAME": ["klay"], "PTs": [30], "junk": [1]})
        out, report = std.standardize(df, "nba")
        assert "player" in out.columns
        assert "points" in out.columns
        assert "junk" in out.columns  # untouched

    def test_default_copy_not_inplace(self, tmp_path):
        std = make_standardizer(tmp_path)
        df = pd.DataFrame({"pts": [1]})
        out, _ = std.standardize(df, "nba")
        assert "pts" in df.columns  # original untouched


class TestAddAlias:
    def test_add_new_alias_persists(self, tmp_path):
        std = make_standardizer(tmp_path)
        assert std.add_alias("nba", "steals", "st") is True
        # Reload from disk and confirm
        reloaded = ColumnStandardizer(config_path=std.config_path)
        assert "st" in reloaded.aliases["nba"]["steals"]

    def test_duplicate_alias_returns_false(self, tmp_path):
        std = make_standardizer(tmp_path)
        assert std.add_alias("nba", "steals", "st") is True
        assert std.add_alias("nba", "steals", "st") is False

    def test_unknown_sport_added(self, tmp_path):
        std = make_standardizer(tmp_path)
        assert std.add_alias("nhl", "goals", "g") is True
        assert std.aliases["nhl"]["goals"] == ["g"]


class TestRealConfig:
    """Sanity checks against the real repo config (backend/configs/column_aliases.yaml)."""

    def test_nba_expected_columns(self):
        std = ColumnStandardizer()
        cols = std.get_expected_columns("nba")
        assert "points" in cols
        assert "assists" in cols

    def test_nfl_expected_columns(self):
        std = ColumnStandardizer()
        cols = std.get_expected_columns("nfl")
        assert "passing_yards" in cols

    def test_real_config_maps_kaggle_aliases(self):
        std = ColumnStandardizer()
        df = pd.DataFrame(columns=["PTS", "AST", "TM"])
        out, _ = std.standardize(df, "nba")
        assert "points" in out.columns
        assert "assists" in out.columns
        assert "team" in out.columns
