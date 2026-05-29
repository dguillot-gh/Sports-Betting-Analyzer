"""
NHL API Endpoints
"""

from fastapi import APIRouter, Request, Query, BackgroundTasks
from typing import Optional, Dict, Any
import logging
from scripts.nhl_odds import get_todays_nhl_odds, SPORTSBOOKS
from scripts.nhl_predictor import analyze_matchup_dual
from scripts.nhl_xgb_trainer import train_nhl_model, get_trainer
from scripts.nhl_backtesting import run_nhl_backtest
from api.json_utils import sanitize_for_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nhl", tags=["nhl"])

@router.get("/odds")
async def get_nhl_odds(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
):
    """Get today's NHL betting odds."""
    return await get_todays_nhl_odds(sportsbook)

@router.get("/sportsbooks")
async def list_nhl_sportsbooks(request: Request):
    """List all supported NHL sportsbooks."""
    return {"sportsbooks": SPORTSBOOKS}

@router.post("/predict")
async def predict_nhl_game(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    spread: float = Query(None, description="Point spread"),
    over_under: float = Query(None, description="Over/under total"),
    home_ml: int = Query(None, description="Home team moneyline"),
    away_ml: int = Query(None, description="Away team moneyline")
):
    """Predict NHL game outcome."""
    return sanitize_for_json(await analyze_matchup_dual(home_team, away_team, spread, over_under, home_ml, away_ml))

@router.post("/analyze-all")
async def analyze_all_nhl_games(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """Fetch today's NHL games and run predictions on all of them."""
    odds_data = await get_todays_nhl_odds(sportsbook)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    analyzed_games = []
    for game in odds_data["games"]:
        try:
            prediction = await analyze_matchup_dual(
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
            logger.error(f"Error analyzing all matchups: {e}")
            analyzed_games.append({**game, "prediction_error": str(e)}) # Keep original error handling for individual games
            
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False))
    })


@router.post("/train")
async def train_xgb_model(
    epochs: int = Query(300, description="Number of training epochs")
):
    """
    Train NHL XGBoost model with walk-forward validation.
    Returns training metrics including cross-validation accuracy.
    """
    try:
        logger.info(f"Starting NHL XGBoost training with {epochs} epochs...")
        result = await train_nhl_model(epochs=epochs)
        return sanitize_for_json(result)
    except Exception as e:
        logger.error(f"Error training NHL model: {e}")
        return {"error": str(e)}


@router.get("/backtest")
async def backtest_model(
    min_edge: float = Query(0.05, description="Minimum edge to place bet (0.05 = 5%)"),
    stake: float = Query(100.0, description="Stake per bet"),
    use_kelly: bool = Query(False, description="Use Kelly criterion for sizing")
):
    """
    Run comprehensive backtest on NHL XGBoost model.
    Returns ROI, Sharpe ratio, win rate, and bet history.
    """
    try:
        logger.info(f"Running NHL backtest (min_edge={min_edge}, stake={stake})...")
        result = await run_nhl_backtest(
            min_edge=min_edge,
            stake=stake,
            use_kelly=use_kelly
        )
        return sanitize_for_json(result)
    except Exception as e:
        logger.error(f"Error running NHL backtest: {e}")
        return {"error": str(e)}


@router.get("/predict-xgb")
async def predict_with_xgb_endpoint(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name")
):
    """
    Get XGBoost model prediction for a matchup.
    Returns win probability and predicted total.
    """
    try:
        import asyncio
        from scripts.nhl_predictor import get_team_advanced_stats
        from scripts.nhl_xgb_trainer import predict_with_xgb as xgb_predict
        
        # Get team stats
        home_stats, away_stats = await asyncio.gather(
            get_team_advanced_stats(home_team),
            get_team_advanced_stats(away_team)
        )
        
        # Get XGB prediction
        result = await xgb_predict(home_team, away_team, home_stats, away_stats)
        
        if result:
            return sanitize_for_json(result)
        else:
            return {"error": "XGBoost model not available. Train the model first using /nhl/train"}
            
    except Exception as e:
        logger.error(f"Error getting XGB prediction: {e}")
        return {"error": str(e)}
