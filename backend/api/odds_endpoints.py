"""
Live Odds API Endpoints
Fetches real-time betting lines from sportsbooks
"""

from fastapi import APIRouter, Query
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/odds", tags=["odds"])


@router.get("/nba")
async def get_nba_odds(
    sportsbook: str = Query("fanduel", description="Sportsbook to fetch odds from"),
):
    """
    Get today's NBA betting odds from specified sportsbook.
    
    Supported sportsbooks: fanduel, draftkings, betmgm, pointsbet, caesars, wynn, bet_rivers_ny
    """
    from scripts.nba_odds import get_todays_nba_odds
    return await get_todays_nba_odds(sportsbook)


@router.get("/nba/compare")
async def compare_nba_odds():
    """
    Get NBA odds from all available sportsbooks for line shopping.
    """
    from scripts.nba_odds import get_all_sportsbook_odds
    return await get_all_sportsbook_odds()


@router.get("/nba/sportsbooks")
async def list_sportsbooks():
    """List all supported sportsbooks."""
    from scripts.nba_odds import SPORTSBOOKS
    return {"sportsbooks": SPORTSBOOKS}


@router.get("/nba/calculate-kelly")
async def calculate_kelly_bet(
    win_probability: float = Query(..., ge=0, le=1, description="Model's predicted win probability (0-1)"),
    american_odds: int = Query(..., description="American odds (e.g., -110, +150)"),
    bankroll: float = Query(1000, description="Total bankroll amount")
):
    """
    Calculate optimal bet size using Kelly Criterion.
    
    Returns recommended bet amount based on model edge vs market odds.
    """
    from scripts.nba_odds import calculate_kelly_criterion, calculate_implied_probability
    
    implied_prob = calculate_implied_probability(american_odds)
    model_edge = (win_probability * 100) - implied_prob
    bet_amount = calculate_kelly_criterion(win_probability, american_odds, bankroll)
    
    return {
        "win_probability": win_probability,
        "american_odds": american_odds,
        "implied_probability": round(implied_prob, 2),
        "model_edge": round(model_edge, 2),
        "recommended_bet": bet_amount,
        "bankroll": bankroll,
        "bet_percentage": round(bet_amount / bankroll * 100, 2) if bankroll > 0 else 0
    }
