import pandas as pd
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Global cache for NBA team stats DataFrame
_nba_df: Optional[pd.DataFrame] = None
_last_updated: Optional[float] = None

def set_nba_df(df: pd.DataFrame):
    global _nba_df, _last_updated
    import time
    _nba_df = df
    _last_updated = time.time()
    logger.info(f"NBA Shared Cache updated with {len(df)} teams")

def get_nba_df() -> Optional[pd.DataFrame]:
    global _nba_df, _last_updated
    import time
    # Cache for 1 hour
    if _nba_df is not None and _last_updated is not None:
        if time.time() - _last_updated < 3600:
            return _nba_df
    return None
