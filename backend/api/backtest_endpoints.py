"""
Backtesting API Endpoints
Test betting strategies on historical data
"""

from fastapi import APIRouter
from scripts.backtesting import BacktestRequest, BacktestResult, run_backtest
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("", response_model=BacktestResult)
async def run_backtest_endpoint(request: BacktestRequest):
    """
    Run a backtest on historical data for the specified sport.
    
    Supports:
    - NBA: Backtest on historical game data
    - NFL: Backtest on historical season data
    - NASCAR: Backtest using race simulations
    
    Strategy parameters:
    - min_edge: Minimum edge % to place bet (default 5%)
    - min_odds/max_odds: Filter bets by odds range
    - stake_type: "flat" for fixed stake
    - stake_amount: Amount per bet
    """
    try:
        result = await run_backtest(request)
        return result
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        raise


@router.get("/seasons/{sport}")
async def get_available_seasons(sport: str):
    """
    Get available seasons for backtesting a sport.
    """
    seasons = {
        "nba": ["2024-25", "2023-24", "2022-23", "2021-22", "2020-21"],
        "nfl": ["2025", "2024", "2023", "2022", "2021", "2020"],
        "nascar": ["2026", "2025", "2024", "2023", "2022"]
    }
    return {
        "sport": sport,
        "seasons": seasons.get(sport.lower(), [])
    }


@router.get("/bet-types/{sport}")
async def get_bet_types(sport: str):
    """
    Get available bet types for backtesting a sport.
    """
    bet_types = {
        "nba": ["moneyline", "spread", "over_under"],
        "nfl": ["moneyline", "spread", "over_under"],
        "nascar": ["race_winner", "top5", "top10"]
    }
    return {
        "sport": sport,
        "bet_types": bet_types.get(sport.lower(), [])
    }
