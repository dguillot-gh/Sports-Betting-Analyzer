"""
Unified data loading utilities for all sports.
"""
from pathlib import Path
from typing import Optional
import pandas as pd
from sports.base import BaseSport


def load_sport_data(sport: BaseSport) -> pd.DataFrame:
    """Load data for a given sport implementation."""
    return sport.load_data()


def chronological_split(df: pd.DataFrame, test_start_season: Optional[int] = None,
                       time_column: str = 'schedule_season') -> tuple:
    """
    Split dataframe chronologically by season.

    Args:
        df: DataFrame to split
        test_start_season: Season year where test set starts
        time_column: Column name containing season/year information

    Returns:
        Tuple of (train_df, test_df, test_start_season)
    """
    seasons = sorted(df[time_column].dropna().unique())
    if not seasons:
        raise ValueError(f'No seasons available in column {time_column}')

    if test_start_season is None:
        # Use the last 10 seasons for testing if available, else last 20% of seasons
        if len(seasons) > 15:
            test_start_season = seasons[-10]
        else:
            k = max(1, int(len(seasons) * 0.2))
            test_start_season = seasons[-k]

    train = df[df[time_column] < test_start_season].copy()
    test = df[df[time_column] >= test_start_season].copy()

    return train, test, test_start_season
