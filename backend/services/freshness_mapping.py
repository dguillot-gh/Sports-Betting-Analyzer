"""Mapping between sports-table names and import-log job names.

The nightly scheduler logs under *job* names (``mlb_results``, ``ncaab``,
``nascar_supplemental``…) while the sports table uses canonical names
(``mlb``, ``college_football``…). The old freshness code looked import logs
up by exact sports-table name, so MLB (imported daily) showed as "never"
and CFB/NCAAB never appeared.

This module is pure (no DB) so it can be unit-tested in isolation.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

# Canonical sport name -> job names that import data for it.
# Order is NOT significant; selection is done by data volume + time.
JOB_ALIASES: Dict[str, List[str]] = {
    "mlb": ["mlb", "mlb_results", "mlb_stats", "mlb_training"],
    "college_baseball": ["college_baseball", "cbb", "baseball", "baseball_results", "baseball_training"],
    "nba": ["nba", "nba_backtest"],
    "nfl": ["nfl", "nfl_training"],
    "nhl": ["nhl"],
    "nascar": ["nascar", "nascar_supplemental"],
    "college_football": ["college_football", "cfb"],
    "ncaab": ["ncaab"],
}
# Reverse lookup: job name -> canonical sport (first match wins).
_JOB_TO_SPORT: Dict[str, str] = {}
for _sport, _names in JOB_ALIASES.items():
    for _name in _names:
        _JOB_TO_SPORT.setdefault(_name, _sport)


def job_names_for_sport(sport: str) -> List[str]:
    """Job names that count as imports for a sport (falls back to exact name)."""
    return JOB_ALIASES.get(sport, [sport])


def sport_for_job(job_name: Optional[str]) -> Optional[str]:
    """Canonical sport for an import-log job name, or None if unknown."""
    if not job_name:
        return None
    return _JOB_TO_SPORT.get(job_name)


def pick_best_import(sport: str, import_logs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Choose the import log that best represents a sport's last data refresh.

    Rules (deterministic):
      1. Only consider SUCCESS logs whose job name is an alias of ``sport``.
      2. Prefer the job that brought in the most *new* rows (the job that
         actually refreshed data), then the most total rows, then the most
         recent start_time. Ties keep the first candidate encountered.
      3. Returns None if there is no matching log.
    """
    names = set(job_names_for_sport(sport))

    candidates = [
        log
        for log in import_logs
        if log.get("status", "SUCCESS") == "SUCCESS" and log.get("sport") in names
    ]
    if not candidates:
        return None

    def sort_key(log: Dict[str, Any]) -> tuple:
        new_rows = log.get("new_rows_imported") or 0
        rows = log.get("rows_imported") or 0
        start = log.get("start_time") or ""
        if isinstance(start, datetime):
            start = start.isoformat()
        return (new_rows, rows, str(start))

    # Stable sort: equal keys preserve input order ("first candidate encountered").
    return max(candidates, key=sort_key)


def build_import_map(sport_names: List[str], import_logs: List[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    """Map each canonical sport name to its best import log (or None)."""
    return {sport: pick_best_import(sport, import_logs) for sport in sport_names}
