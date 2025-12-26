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


@router.post("/nba/predict")
async def predict_game(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    spread: float = Query(None, description="Point spread (away team perspective)"),
    over_under: float = Query(None, description="Over/under total"),
    home_ml: int = Query(None, description="Home team moneyline"),
    away_ml: int = Query(None, description="Away team moneyline")
):
    """
    Predict game outcome with value bet detection.
    """
    from scripts.nba_predictor import analyze_matchup
    return await analyze_matchup(home_team, away_team, spread, over_under, home_ml, away_ml)


@router.post("/nba/predict-dual")
async def predict_game_dual(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    spread: float = Query(None, description="Point spread"),
    over_under: float = Query(None, description="Over/under total"),
    home_ml: int = Query(None, description="Home team moneyline"),
    away_ml: int = Query(None, description="Away team moneyline")
):
    """
    Predict with BOTH simple and XGBoost models for comparison.
    """
    from scripts.nba_predictor import analyze_matchup_dual
    return await analyze_matchup_dual(home_team, away_team, spread, over_under, home_ml, away_ml)


@router.post("/nba/train")
async def train_nba_model(epochs: int = Query(500, description="Training epochs")):
    """
    Train XGBoost model on historical data.
    """
    from scripts.nba_xgb_trainer import train_nba_model
    return await train_nba_model(epochs)



@router.post("/nba/analyze-all")
async def analyze_all_games(
    sportsbook: str = Query("fanduel", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's games and run predictions on all of them.
    Returns games with predictions and value bet flags.
    """
    from scripts.nba_odds import get_todays_nba_odds
    from scripts.nba_predictor import analyze_matchup
    
    # Get today's odds
    odds_data = await get_todays_nba_odds(sportsbook)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    # Analyze each game
    analyzed_games = []
    for game in odds_data["games"]:
        try:
            prediction = await analyze_matchup(
                home_team=game.get("home_team", ""),
                away_team=game.get("away_team", ""),
                spread=game.get("spread"),
                over_under=game.get("over_under"),
                home_ml=game.get("home_moneyline"),
                away_ml=game.get("away_moneyline")
            )
            
            # Combine odds data with prediction
            analyzed_game = {**game, **prediction}
            analyzed_games.append(analyzed_game)
            
        except Exception as e:
            logger.error(f"Error analyzing game: {e}")
            analyzed_games.append({**game, "prediction_error": str(e)})
    
    return {
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False))
    }


# =========== NFL ENDPOINTS ===========

@router.get("/nfl")
async def get_nfl_odds(
    sportsbook: str = Query("fanduel", description="Sportsbook to fetch odds from"),
):
    """
    Get today's NFL betting odds from specified sportsbook.
    """
    from scripts.nfl_predictor import get_todays_nfl_odds
    return await get_todays_nfl_odds(sportsbook)


@router.post("/nfl/predict")
async def predict_nfl_game(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    spread: float = Query(None, description="Point spread (away team perspective)"),
    over_under: float = Query(None, description="Over/under total"),
    home_ml: int = Query(None, description="Home team moneyline"),
    away_ml: int = Query(None, description="Away team moneyline")
):
    """
    Predict NFL game outcome with value bet detection.
    """
    from scripts.nfl_predictor import analyze_nfl_matchup
    return await analyze_nfl_matchup(home_team, away_team, spread, over_under, home_ml, away_ml)


@router.post("/nfl/analyze-all")
async def analyze_all_nfl_games(
    sportsbook: str = Query("fanduel", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's NFL games and run predictions on all of them.
    """
    from scripts.nfl_predictor import get_todays_nfl_odds, analyze_nfl_matchup
    
    odds_data = await get_todays_nfl_odds(sportsbook)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    analyzed_games = []
    for game in odds_data["games"]:
        try:
            prediction = await analyze_nfl_matchup(
                home_team=game.get("home_team", ""),
                away_team=game.get("away_team", ""),
                spread=game.get("spread"),
                over_under=game.get("over_under"),
                home_ml=game.get("home_moneyline"),
                away_ml=game.get("away_moneyline")
            )
            analyzed_game = {**game, **prediction}
            analyzed_games.append(analyzed_game)
        except Exception as e:
            logger.error(f"Error analyzing NFL game: {e}")
            analyzed_games.append({**game, "prediction_error": str(e)})
    
    return {
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
        "epa_loaded": True  # EPA is loaded from nflreadpy on each analysis
    }


@router.post("/nfl/train")
async def train_nfl_model(epochs: int = Query(500, description="Training epochs")):
    """
    Train NFL XGBoost model on historical data.
    """
    from scripts.nfl_xgb_trainer import train_nfl_model
    return await train_nfl_model(epochs)


@router.post("/nfl/predict-dual")
async def predict_nfl_game_dual(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    spread: float = Query(None, description="Point spread"),
    over_under: float = Query(None, description="Over/under total"),
    home_ml: int = Query(None, description="Home team moneyline"),
    away_ml: int = Query(None, description="Away team moneyline")
):
    """
    Predict NFL game with BOTH simple and XGBoost models.
    """
    from scripts.nfl_predictor import analyze_nfl_matchup_dual
    return await analyze_nfl_matchup_dual(home_team, away_team, spread, over_under, home_ml, away_ml)

