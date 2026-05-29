"""
Live Odds API Endpoints
Fetches real-time betting lines from sportsbooks
"""

from fastapi import APIRouter, Query, Request, UploadFile, File
from typing import Optional
import logging
from datetime import datetime
from src.ops_alerts import OpsAlertService
from api.json_utils import sanitize_for_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/odds", tags=["odds"])


@router.get("/nba")
async def get_nba_odds(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
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


@router.get("/nba/compare/fd-dk")
async def compare_fanduel_draftkings():
    """
    Compare odds between FanDuel and DraftKings only.
    Returns games with both books' odds and highlights the better line.
    """
    from scripts.nba_odds import get_todays_nba_odds
    
    # Fetch from both books
    fd_odds = await get_todays_nba_odds("fanduel")
    dk_odds = await get_todays_nba_odds("draftkings")
    
    if fd_odds.get("error") or dk_odds.get("error"):
        return {"error": "Could not fetch odds from one or both sportsbooks"}
    
    # Combine odds by game
    fd_games = {f"{g['away_team']} @ {g['home_team']}": g for g in fd_odds.get("games", [])}
    dk_games = {f"{g['away_team']} @ {g['home_team']}": g for g in dk_odds.get("games", [])}
    
    combined_games = []
    for game_key in set(fd_games.keys()) | set(dk_games.keys()):
        fd_game = fd_games.get(game_key, {})
        dk_game = dk_games.get(game_key, {})
        
        game_data = {
            "game": game_key,
            "home_team": fd_game.get("home_team") or dk_game.get("home_team"),
            "away_team": fd_game.get("away_team") or dk_game.get("away_team"),
            "game_time": fd_game.get("game_time") or dk_game.get("game_time"),
            "fanduel": {
                "home_ml": fd_game.get("home_moneyline"),
                "away_ml": fd_game.get("away_moneyline"),
                "spread": fd_game.get("spread"),
                "over_under": fd_game.get("over_under"),
            },
            "draftkings": {
                "home_ml": dk_game.get("home_moneyline"),
                "away_ml": dk_game.get("away_moneyline"),
                "spread": dk_game.get("spread"),
                "over_under": dk_game.get("over_under"),
            },
            "best": {}
        }
        
        # Determine best lines (higher odds = better for bettor)
        # Home ML
        fd_home = fd_game.get("home_moneyline")
        dk_home = dk_game.get("home_moneyline")
        if fd_home and dk_home:
            game_data["best"]["home_ml"] = "fanduel" if fd_home > dk_home else "draftkings" if dk_home > fd_home else "same"
        
        # Away ML
        fd_away = fd_game.get("away_moneyline")
        dk_away = dk_game.get("away_moneyline")
        if fd_away and dk_away:
            game_data["best"]["away_ml"] = "fanduel" if fd_away > dk_away else "draftkings" if dk_away > fd_away else "same"
        
        # Over/Under (same number is better, we just note if different)
        fd_ou = fd_game.get("over_under")
        dk_ou = dk_game.get("over_under")
        if fd_ou and dk_ou:
            game_data["best"]["over_under"] = "same" if fd_ou == dk_ou else "different"
            game_data["ou_diff"] = abs(fd_ou - dk_ou) if fd_ou != dk_ou else 0
        
        combined_games.append(game_data)
    
    return {
        "date": fd_odds.get("date"),
        "games": combined_games,
        "count": len(combined_games)
    }


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
    return sanitize_for_json(await analyze_matchup(home_team, away_team, spread, over_under, home_ml, away_ml))


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
    return sanitize_for_json(await analyze_matchup_dual(home_team, away_team, spread, over_under, home_ml, away_ml))


@router.post("/nba/train")
async def train_nba_model(epochs: int = Query(500, description="Training epochs")):
    """
    Train XGBoost model on historical data.
    """
    from scripts.nba_xgb_trainer import train_nba_model
    return await train_nba_model(epochs)



@router.post("/nba/analyze-all")
async def analyze_all_games(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's games and run predictions on all of them.
    Returns BOTH simple model and XGBoost predictions for side-by-side comparison.
    """
    from scripts.nba_odds import get_todays_nba_odds
    from scripts.nba_predictor import analyze_matchup_dual
    
    # Get today's odds
    odds_data = await get_todays_nba_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("nba/analyze-all", odds_data)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    # Analyze each game with both models
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
            
            # Combine odds data with prediction
            analyzed_game = {**game, **prediction}
            analyzed_games.append(analyzed_game)
            
        except Exception as e:
            logger.error(f"Error analyzing game: {e}")
            analyzed_games.append({**game, "prediction_error": str(e)})
    
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
        "xgb_available": any(g.get("xgboost_model") and not g.get("xgboost_model", {}).get("error") for g in analyzed_games)
    })


# =========== NFL ENDPOINTS ===========

@router.get("/nfl")
async def get_nfl_odds(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
):
    """
    Get today's NFL betting odds from specified sportsbook.
    """
    from scripts.nfl_predictor import get_todays_nfl_odds
    return await get_todays_nfl_odds(sportsbook)


@router.get("/nfl/compare/fd-dk")
async def compare_nfl_fanduel_draftkings():
    """
    Compare NFL odds between FanDuel and DraftKings.
    """
    from scripts.nfl_predictor import get_todays_nfl_odds
    
    fd_odds = await get_todays_nfl_odds("fanduel")
    dk_odds = await get_todays_nfl_odds("draftkings")
    
    if fd_odds.get("error") or dk_odds.get("error"):
        return {"error": "Could not fetch odds from one or both sportsbooks"}
    
    fd_games = {f"{g.get('away_team', '')} @ {g.get('home_team', '')}": g for g in fd_odds.get("games", [])}
    dk_games = {f"{g.get('away_team', '')} @ {g.get('home_team', '')}": g for g in dk_odds.get("games", [])}
    
    combined_games = []
    for game_key in set(fd_games.keys()) | set(dk_games.keys()):
        fd_game = fd_games.get(game_key, {})
        dk_game = dk_games.get(game_key, {})
        
        game_data = {
            "game": game_key,
            "home_team": fd_game.get("home_team") or dk_game.get("home_team"),
            "away_team": fd_game.get("away_team") or dk_game.get("away_team"),
            "game_time": fd_game.get("game_time") or dk_game.get("game_time"),
            "fanduel": {
                "home_ml": fd_game.get("home_moneyline"),
                "away_ml": fd_game.get("away_moneyline"),
                "spread": fd_game.get("spread"),
                "over_under": fd_game.get("over_under"),
            },
            "draftkings": {
                "home_ml": dk_game.get("home_moneyline"),
                "away_ml": dk_game.get("away_moneyline"),
                "spread": dk_game.get("spread"),
                "over_under": dk_game.get("over_under"),
            },
            "best": {}
        }
        
        # Determine best lines
        fd_home = fd_game.get("home_moneyline")
        dk_home = dk_game.get("home_moneyline")
        if fd_home and dk_home:
            game_data["best"]["home_ml"] = "fanduel" if fd_home > dk_home else "draftkings" if dk_home > fd_home else "same"
        
        fd_away = fd_game.get("away_moneyline")
        dk_away = dk_game.get("away_moneyline")
        if fd_away and dk_away:
            game_data["best"]["away_ml"] = "fanduel" if fd_away > dk_away else "draftkings" if dk_away > fd_away else "same"
        
        combined_games.append(game_data)
    
    return {
        "date": fd_odds.get("date"),
        "games": combined_games,
        "count": len(combined_games)
    }


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
    return sanitize_for_json(await analyze_nfl_matchup(home_team, away_team, spread, over_under, home_ml, away_ml))


@router.post("/nfl/analyze-all")
async def analyze_all_nfl_games(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's NFL games and run predictions on all of them.
    Returns BOTH simple model and XGBoost predictions for side-by-side comparison.
    """
    from scripts.nfl_predictor import get_todays_nfl_odds, analyze_nfl_matchup_dual
    
    odds_data = await get_todays_nfl_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("nfl/analyze-all", odds_data)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    analyzed_games = []
    for game in odds_data["games"]:
        try:
            # Use dual prediction to get both simple and XGB models
            prediction = await analyze_nfl_matchup_dual(
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
    
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
        "xgb_available": any(g.get("xgboost_model") and not g.get("xgboost_model", {}).get("error") for g in analyzed_games),
        "epa_loaded": True
    })


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
    return sanitize_for_json(await analyze_nfl_matchup_dual(home_team, away_team, spread, over_under, home_ml, away_ml))


# =========== CACHE-INTEGRATED ENDPOINTS ===========
# These endpoints auto-cache results and merge with previously cached games

@router.post("/nfl/analyze-cached")
async def analyze_nfl_with_cache(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
    include_cached: bool = Query(True, description="Include previously cached games")
):
    """
    Fetch today's NFL games, run predictions, cache results, and merge with any
    previously cached games that are no longer in the live API response.
    
    This prevents late-night games from disappearing on page refresh.
    """
    from scripts.nfl_predictor import get_todays_nfl_odds, analyze_nfl_matchup_dual
    
    # Step 1: Get fresh odds
    odds_data = await get_todays_nfl_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("nfl/analyze-cached", odds_data)
    
    analyzed_games = []
    fresh_game_ids = []
    
    if not odds_data.get("error") and odds_data.get("games"):
        # Step 2: Analyze fresh games
        for game in odds_data["games"]:
            try:
                prediction = await analyze_nfl_matchup_dual(
                    home_team=game.get("home_team", ""),
                    away_team=game.get("away_team", ""),
                    spread=game.get("spread"),
                    over_under=game.get("over_under"),
                    home_ml=game.get("home_moneyline"),
                    away_ml=game.get("away_moneyline")
                )
                analyzed_game = {**game, **prediction, "is_cached": False}
                analyzed_games.append(analyzed_game)
                
                # Track game ID for cache exclusion
                game_id = f"nfl_{game.get('home_team', '')}_{game.get('away_team', '')}_{game.get('game_time', '')}"
                fresh_game_ids.append(game_id)
                analyzed_game["id"] = game_id
                
            except Exception as e:
                logger.error(f"Error analyzing NFL game: {e}")
                analyzed_game = {**game, "prediction_error": str(e), "is_cached": False}
                analyzed_games.append(analyzed_game)
        
        # Step 3: Cache the fresh results
        try:
            from src.odds_cache import get_cache_service
            cache = get_cache_service()
            
            games_to_cache = []
            for g in analyzed_games:
                games_to_cache.append({
                    "id": g.get("id"),
                    "game_time": g.get("game_time"),
                    "home_team": g.get("home_team"),
                    "away_team": g.get("away_team"),
                    "spread": g.get("spread"),
                    "over_under": g.get("over_under"),
                    "home_moneyline": g.get("home_moneyline"),
                    "away_moneyline": g.get("away_moneyline"),
                    "simple_model": g.get("simple_model"),
                    "xgboost_model": g.get("xgboost_model"),
                    "has_value": g.get("has_value", False),
                })
            
            await cache.store_games("nfl", games_to_cache)
            logger.info(f"Cached {len(games_to_cache)} NFL games")
            
        except Exception as e:
            logger.warning(f"Failed to cache games: {e}")
    
    # Step 4: Merge with cached games if requested
    cached_count = 0
    if include_cached:
        try:
            from src.odds_cache import get_cache_service
            cache = get_cache_service()
            
            cached_games = await cache.get_cached_games("nfl", exclude_ids=fresh_game_ids, include_expired=False)
            current_date_str = str(odds_data.get("date", ""))
            
            for cg in cached_games:
                game_time = cg.get("game_date")
                if game_time and current_date_str and not str(game_time).startswith(current_date_str):
                    continue
                
                # Convert cached format back to display format
                odds_data_cached = cg.get("odds_data", {})
                analysis_cached = cg.get("analysis", {})
                
                restored_game = {
                    "id": cg.get("game_id"),
                    "home_team": cg.get("home_team"),
                    "away_team": cg.get("away_team"),
                    "game_time": cg.get("game_date"),
                    "spread": odds_data_cached.get("spread"),
                    "over_under": odds_data_cached.get("over_under"),
                    "home_moneyline": odds_data_cached.get("home_moneyline"),
                    "away_moneyline": odds_data_cached.get("away_moneyline"),
                    "simple_model": analysis_cached.get("simple_model"),
                    "xgboost_model": analysis_cached.get("xgboost_model"),
                    "has_value": analysis_cached.get("has_value", False),
                    "is_cached": True,
                    "cached_at": cg.get("fetched_at"),
                }
                analyzed_games.append(restored_game)
                cached_count += 1
                
        except Exception as e:
            logger.warning(f"Failed to retrieve cached games: {e}")
    
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "fresh_count": len(analyzed_games) - cached_count,
        "cached_count": cached_count,
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
        "xgb_available": any(g.get("xgboost_model") and not g.get("xgboost_model", {}).get("error") for g in analyzed_games),
    })


@router.post("/nba/analyze-cached")
async def analyze_nba_with_cache(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
    include_cached: bool = Query(True, description="Include previously cached games")
):
    """
    Fetch today's NBA games, run predictions, cache results, and merge with any
    previously cached games that are no longer in the live API response.
    
    This prevents late-night games from disappearing on page refresh.
    """
    from scripts.nba_odds import get_todays_nba_odds
    from scripts.nba_predictor import analyze_matchup_dual
    
    # Step 1: Get fresh odds
    odds_data = await get_todays_nba_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("nba/analyze-cached", odds_data)
    logger.info(f"NBA odds fetch: {len(odds_data.get('games', []))} games, error={odds_data.get('error')}, message={odds_data.get('message')}")
    
    analyzed_games = []
    fresh_game_ids = []
    
    if not odds_data.get("error") and odds_data.get("games"):
        # Step 2: Analyze fresh games
        for game in odds_data["games"]:
            game_id = f"nba_{game.get('home_team', '')}_{game.get('away_team', '')}_{game.get('game_time', '')}"
            fresh_game_ids.append(game_id)
            try:
                prediction = await analyze_matchup_dual(
                    home_team=game.get("home_team", ""),
                    away_team=game.get("away_team", ""),
                    spread=game.get("spread"),
                    over_under=game.get("over_under"),
                    home_ml=game.get("home_moneyline"),
                    away_ml=game.get("away_moneyline")
                )
                analyzed_game = {**game, **prediction, "is_cached": False, "id": game_id}
                analyzed_games.append(analyzed_game)
                
            except Exception as e:
                logger.warning(f"Error analyzing NBA game {game.get('home_team')} vs {game.get('away_team')}: {e}")
                analyzed_game = {**game, "prediction_error": str(e), "is_cached": False, "id": game_id}
                analyzed_games.append(analyzed_game)
        
        # Step 3: Cache the fresh results
        try:
            from src.odds_cache import get_cache_service
            cache = get_cache_service()
            
            games_to_cache = []
            for g in analyzed_games:
                games_to_cache.append({
                    "id": g.get("id"),
                    "game_time": g.get("game_time"),
                    "home_team": g.get("home_team"),
                    "away_team": g.get("away_team"),
                    "spread": g.get("spread"),
                    "over_under": g.get("over_under"),
                    "home_moneyline": g.get("home_moneyline"),
                    "away_moneyline": g.get("away_moneyline"),
                    "simple_model": g.get("simple_model"),
                    "xgboost_model": g.get("xgboost_model"),
                    "has_value": g.get("has_value", False),
                })
            
            await cache.store_games("nba", games_to_cache)
            logger.info(f"Cached {len(games_to_cache)} NBA games")
            
        except Exception as e:
            logger.warning(f"Failed to cache games: {e}")
    
    # Step 4: Merge with cached games if requested
    cached_count = 0
    if include_cached:
        try:
            from src.odds_cache import get_cache_service
            cache = get_cache_service()
            
            cached_games = await cache.get_cached_games("nba", exclude_ids=fresh_game_ids, include_expired=False)
            current_date_str = str(odds_data.get("date", ""))
            
            for cg in cached_games:
                game_time = cg.get("game_date")
                if game_time and current_date_str and not str(game_time).startswith(current_date_str):
                    continue
                
                odds_data_cached = cg.get("odds_data", {})
                analysis_cached = cg.get("analysis", {})
                
                restored_game = {
                    "id": cg.get("game_id"),
                    "home_team": cg.get("home_team"),
                    "away_team": cg.get("away_team"),
                    "game_time": cg.get("game_date"),
                    "spread": odds_data_cached.get("spread"),
                    "over_under": odds_data_cached.get("over_under"),
                    "home_moneyline": odds_data_cached.get("home_moneyline"),
                    "away_moneyline": odds_data_cached.get("away_moneyline"),
                    "simple_model": analysis_cached.get("simple_model"),
                    "xgboost_model": analysis_cached.get("xgboost_model"),
                    "has_value": analysis_cached.get("has_value", False),
                    "is_cached": True,
                    "cached_at": cg.get("fetched_at"),
                }
                analyzed_games.append(restored_game)
                cached_count += 1
                
        except Exception as e:
            logger.warning(f"Failed to retrieve cached games: {e}")
    
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "fresh_count": len(analyzed_games) - cached_count,
        "cached_count": cached_count,
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
        "xgb_available": any(g.get("xgboost_model") and not g.get("xgboost_model", {}).get("error") for g in analyzed_games),
    })


# ========================================================
# NCAAB (Men's College Basketball) Endpoints
# ========================================================

@router.get("/ncaab")
async def get_ncaab_odds(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
):
    """
    Get today's NCAAB betting odds from specified sportsbook.
    
    Supported sportsbooks: fanduel, draftkings, betmgm, pointsbet, caesars
    """
    from scripts.ncaab_predictor import get_todays_ncaab_odds
    return await get_todays_ncaab_odds(sportsbook)


@router.post("/ncaab/predict")
async def predict_ncaab_game(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    spread: float = Query(None, description="Point spread"),
    over_under: float = Query(None, description="Over/under total"),
    home_ml: int = Query(None, description="Home team moneyline"),
    away_ml: int = Query(None, description="Away team moneyline")
):
    """
    Predict NCAAB game outcome with value bet detection.
    """
    from scripts.ncaab_predictor import analyze_ncaab_matchup
    return sanitize_for_json(await analyze_ncaab_matchup(home_team, away_team, spread, over_under, home_ml, away_ml))


@router.post("/ncaab/analyze-all")
async def analyze_all_ncaab_games(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's NCAAB games and run predictions on all of them.
    """
    from scripts.ncaab_predictor import get_todays_ncaab_odds, analyze_ncaab_matchup
    
    odds_data = await get_todays_ncaab_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("ncaab/analyze-all", odds_data)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    analyzed_games = []
    for game in odds_data["games"]:
        try:
            prediction = await analyze_ncaab_matchup(
                home_team=game.get("home_team", ""),
                away_team=game.get("away_team", ""),
                spread=game.get("spread"),
                over_under=game.get("over_under"),
                home_ml=game.get("home_moneyline"),
                away_ml=game.get("away_moneyline")
            )
            
            game_data = {
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "game_time": game.get("game_time"),
                "status": game.get("status"),
                "spread": game.get("spread"),
                "over_under": game.get("over_under"),
                "home_moneyline": game.get("home_moneyline"),
                "away_moneyline": game.get("away_moneyline"),
                "prediction": prediction,
                "has_value": prediction.get("has_value", False),
                "value_bets": prediction.get("value_bets", []),
            }
            analyzed_games.append(game_data)
        except Exception as e:
            logger.warning(f"Error analyzing NCAAB game {game.get('home_team')} vs {game.get('away_team')}: {e}")
            analyzed_games.append({**game, "error": str(e)})
    
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "source": odds_data.get("source"),
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
    })



# ========================================================
# College Baseball Endpoints
# ========================================================

@router.get("/college-baseball")
async def get_college_baseball_odds(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
):
    """
    Get today's College Baseball betting odds.
    """
    from scripts.college_baseball_predictor import get_todays_college_baseball_odds
    return await get_todays_college_baseball_odds(sportsbook)


@router.post("/college-baseball/analyze-all")
async def analyze_all_college_baseball_games(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's College Baseball games and run predictions.
    """
    from scripts.college_baseball_predictor import get_todays_college_baseball_odds, analyze_college_baseball_matchup
    
    odds_data = await get_todays_college_baseball_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("college-baseball/analyze-all", odds_data)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    analyzed_games = []
    for game in odds_data["games"]:
        try:
            prediction = await analyze_college_baseball_matchup(
                home_team=game.get("home_team", ""),
                away_team=game.get("away_team", ""),
                spread=game.get("spread"),
                over_under=game.get("over_under"),
                home_ml=game.get("home_moneyline"),
                away_ml=game.get("away_moneyline")
            )
            
            game_data = {
                "home_team": game.get("home_team"),
                "away_team": game.get("away_team"),
                "game_time": game.get("game_time"),
                "status": game.get("status"),
                "spread": game.get("spread"),
                "over_under": game.get("over_under"),
                "home_moneyline": game.get("home_moneyline"),
                "away_moneyline": game.get("away_moneyline"),
                "prediction": prediction,
                "has_value": prediction.get("has_value", False),
                "value_bets": prediction.get("value_bets", []),
            }
            analyzed_games.append(game_data)
        except Exception as e:
            logger.warning(f"Error analyzing College Baseball game: {e}")
            analyzed_games.append({**game, "error": str(e)})
    
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "source": odds_data.get("source"),
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
    })


@router.post("/college-baseball/scrape-results")
async def scrape_college_baseball_results(
    days_back: int = Query(7, description="Number of days to scrape")
):
    """
    Scrape completed college baseball game results from ESPN
    and store them in the database for the rolling-stats model.
    """
    from scripts.college_baseball_results_scraper import scrape_and_store
    try:
        result = await scrape_and_store(days_back=days_back)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Error scraping results: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/college-baseball/backfill-season")
async def backfill_college_baseball_season(
    year: int = Query(2025, description="Season year to backfill")
):
    """
    Backfill an entire season of college baseball game results.
    Fetches all completed games from Feb-June of the given year.
    """
    from scripts.college_baseball_results_scraper import backfill_season
    try:
        result = await backfill_season(year=year)
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Error backfilling season: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/college-baseball/train-models")
async def train_college_baseball_models(
    mode: str = Query("csv", description="Training mode: 'csv' for stat-based, 'rolling' for DB-based, 'both' for both")
):
    """
    Train/retrain the College Baseball XGBoost models.
    - csv: Retrain stat-based models from multi-year CSV data
    - rolling: Train rolling-stats models from DB game results
    - both: Run both training pipelines
    """
    from scripts.college_baseball_xgb_trainer import CollegeBaseballXGBTrainer
    try:
        trainer = CollegeBaseballXGBTrainer()
        results = {}

        if mode in ("csv", "both"):
            trainer.train_from_csvs()
            results["csv_training"] = "complete"

        if mode in ("rolling", "both"):
            import asyncio
            await trainer.train()
            results["rolling_training"] = "complete"

        return {"status": "success", "mode": mode, **results}
    except Exception as e:
        logger.error(f"Error training models: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/ncaab/update-torvik")
async def update_torvik_data():
    """
    Trigger update of Torvik data (T-Rank ratings) from raw CSV.
    """
    import subprocess
    import sys
    from pathlib import Path
    
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "process_torvik_csv.py"
    
    try:
        # Run the processing script
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=True
        )
        return {"status": "success", "message": "Torvik data updated from CSV", "output": result.stdout}
    except subprocess.CalledProcessError as e:
        logger.error(f"Torvik update failed: {e.stderr}")
        return {"status": "error", "message": "Failed to update Torvik data", "details": e.stderr}
    except Exception as e:
        logger.error(f"Torvik update error: {e}")
        return {"status": "error", "message": str(e)}





@router.post("/ncaab/upload-torvik")
async def upload_torvik_csv(
    file: UploadFile = File(...)
):
    """
    Upload a new raw_torvik.csv file.
    """
    from pathlib import Path
    import shutil
    
    try:
        data_dir = Path(__file__).resolve().parent.parent / "data" / "ncaab"
        data_dir.mkdir(exist_ok=True, parents=True) # Ensure dir exists
        
        file_path = data_dir / "raw_torvik.csv"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {"status": "success", "message": f"Torvik CSV uploaded to {file_path}"}
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return {"status": "error", "message": str(e)}


# ========================================================
# College Football (CFB/NCAAF) Endpoints
# ========================================================

@router.post("/cfb/analyze-all")
async def analyze_all_cfb_games(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's College Football games and run predictions.
    Uses The Odds API (americanfootball_ncaaf) with quota tracking.
    """
    from scripts.cfb_predictor import get_todays_cfb_odds, analyze_cfb_matchup_dual
    
    # 1. Fetch Odds
    odds_data = await get_todays_cfb_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("cfb/analyze-all", odds_data)
    
    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data
    
    # 2. Analyze Games
    analyzed_games = []
    for game in odds_data["games"]:
        try:
            # Dual analysis (Simple + XGB placeholder)
            prediction = await analyze_cfb_matchup_dual(
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
            logger.error(f"Error analyzing CFB game: {e}")
            analyzed_games.append({**game, "prediction_error": str(e)})
            
    # 3. Return Response (including quota)
    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "source": odds_data.get("source"),
        "api_quota": odds_data.get("api_quota"), # Pass through quota info
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
    })

@router.post("/cfb/predict-dual")
async def predict_cfb_dual(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    spread: float = Query(None, description="Point spread"),
    over_under: float = Query(None, description="Over/under total"),
    home_ml: int = Query(None, description="Home team moneyline"),
    away_ml: int = Query(None, description="Away team moneyline")
):
    """
    Predict CFB game with simple model (XGB placeholder).
    """
    from scripts.cfb_predictor import analyze_cfb_matchup_dual
    return sanitize_for_json(await analyze_cfb_matchup_dual(home_team, away_team, spread, over_under, home_ml, away_ml))


# ========================================================
# MLB Endpoints
# ========================================================

@router.get("/mlb")
async def get_mlb_odds(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
):
    """
    Get today's MLB betting odds.
    """
    from scripts.mlb_odds import get_todays_mlb_odds
    return await get_todays_mlb_odds(sportsbook)


@router.post("/mlb/analyze-all")
async def analyze_all_mlb_games(
    request: Request,
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """
    Fetch today's MLB games and run ensemble predictions.
    Includes Pythagorean baseline + XGBoost moneyline/spread/totals when trained.
    """
    from scripts.mlb_odds import get_todays_mlb_odds
    from scripts.mlb_predictor import analyze_mlb_matchup

    odds_data = await get_todays_mlb_odds(sportsbook)
    OpsAlertService.maybe_alert_low_odds_quota("mlb/analyze-all", odds_data)

    if odds_data.get("error") or not odds_data.get("games"):
        return odds_data

    # Get DB pool for feature lookups (optional — graceful fallback)
    pool = getattr(request.app.state, "pool", None)

    # Fetch probable pitchers for today's games
    probable_pitchers = {}
    try:
        from scripts.mlb_stats_collector import fetch_todays_probable_pitchers
        probable_pitchers = await fetch_todays_probable_pitchers()
    except Exception as e:
        logger.warning(f"Could not fetch probable pitchers: {e}")

    analyzed_games = []
    for game in odds_data["games"]:
        try:
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")

            # Match probable pitchers
            pp_key = f"{home_team}||{away_team}"
            pp = probable_pitchers.get(pp_key, {})

            prediction = await analyze_mlb_matchup(
                home_team=home_team,
                away_team=away_team,
                spread=game.get("spread"),
                over_under=game.get("over_under"),
                home_ml=game.get("home_moneyline"),
                away_ml=game.get("away_moneyline"),
                pool=pool,
                home_sp_id=pp.get("home_sp_id"),
                away_sp_id=pp.get("away_sp_id"),
                venue_name=pp.get("venue"),
                is_day_game=pp.get("day_night") == "day",
            )

            game_data = {
                "home_team": home_team,
                "away_team": away_team,
                "game_time": game.get("game_time"),
                "status": game.get("status"),
                "home_score": game.get("home_score"),
                "away_score": game.get("away_score"),
                "spread": game.get("spread"),
                "over_under": game.get("over_under"),
                "home_moneyline": game.get("home_moneyline"),
                "away_moneyline": game.get("away_moneyline"),
                "simple_model": prediction,
                "has_value": prediction.get("has_value", False),
                "value_bets": prediction.get("value_bets", []),
                # New: context from probable pitchers
                "home_sp": pp.get("home_sp_name"),
                "away_sp": pp.get("away_sp_name"),
                "venue": pp.get("venue"),
            }
            analyzed_games.append(game_data)
        except Exception as e:
            logger.warning(f"Error analyzing MLB game: {e}")
            analyzed_games.append({**game, "error": str(e)})

    return sanitize_for_json({
        "date": odds_data.get("date"),
        "sportsbook": sportsbook,
        "games": analyzed_games,
        "count": len(analyzed_games),
        "value_bets_found": sum(1 for g in analyzed_games if g.get("has_value", False)),
    })


@router.get("/mlb/team-stats")
async def get_mlb_team_stats(request: Request):
    """Get all MLB team stats for the current season."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        return {"error": "Database not available"}
    try:
        from scripts.mlb_stats_collector import get_all_team_stats
        from datetime import datetime
        stats = await get_all_team_stats(pool, datetime.utcnow().year)
        return {"season": datetime.utcnow().year, "teams": stats, "count": len(stats)}
    except Exception as e:
        logger.error(f"Error fetching MLB team stats: {e}")
        return {"error": str(e)}


@router.get("/mlb/model-metrics")
async def get_mlb_model_metrics(request: Request):
    """Get latest training metrics for all MLB models."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        return {"error": "Database not available"}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (model_name)
                    model_name, trained_at, train_size, test_size,
                    roc_auc, accuracy, brier_score, log_loss
                FROM mlb_model_runs
                ORDER BY model_name, trained_at DESC
            """)
            models = {dict(r)["model_name"]: dict(r) for r in rows}
            # Convert datetimes to strings
            for m in models.values():
                if m.get("trained_at"):
                    m["trained_at"] = m["trained_at"].isoformat()
            return {"models": models}
    except Exception as e:
        logger.error(f"Error fetching MLB model metrics: {e}")
        return {"error": str(e)}


@router.post("/mlb/import-results")
async def import_mlb_results(request: Request):
    """Trigger on-demand import of completed MLB game results."""
    try:
        from scripts.mlb_results_importer import run_import
        result = await run_import()
        return result
    except Exception as e:
        logger.error(f"MLB results import failed: {e}")
        return {"error": str(e)}


@router.post("/mlb/refresh-stats")
async def refresh_mlb_stats(request: Request):
    """Trigger on-demand MLB data collection."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        return {"error": "Database not available"}
    try:
        from scripts.mlb_stats_collector import run_full_collection
        result = await run_full_collection(pool)
        return result
    except Exception as e:
        logger.error(f"MLB stats refresh failed: {e}")
        return {"error": str(e)}


@router.post("/mlb/train")
async def train_mlb_models(request: Request):
    """Trigger MLB model retraining."""
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        return {"error": "Database not available"}
    try:
        from scripts.mlb_train_models import train_all_models
        from scripts.mlb_predictor import reload_models
        result = await train_all_models(pool)
        if result.get("success"):
            reload_models()
        return result
    except Exception as e:
        logger.error(f"MLB model training failed: {e}")
        return {"error": str(e)}


@router.get("/all-sports/analyze")
async def analyze_all_sports(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from")
):
    """
    Run analysis on ALL sports concurrently.
    Resilient: if one sport fails or has no games, the rest still return.
    """
    import asyncio
    
    async def safe_analyze(sport_name, func, *args, **kwargs):
        try:
            result = await func(*args, **kwargs)
            # If the result is an error dict or has no games, normalize it
            if not result or result.get("error") or not result.get("games"):
                return {"sport": sport_name, "games": [], "count": 0, "value_bets_found": 0, "status": "no_games"}
            
            # Ensure it has the sport name
            result["sport"] = sport_name
            result["status"] = "success"
            return result
        except Exception as e:
            logger.error(f"Error in safe_analyze for {sport_name}: {e}")
            return {"sport": sport_name, "games": [], "count": 0, "value_bets_found": 0, "status": "failed", "error": str(e)}

    # Gather all sports concurrently
    tasks = [
        safe_analyze("nba", analyze_all_games, sportsbook),
        safe_analyze("nfl", analyze_all_nfl_games, sportsbook),
        safe_analyze("ncaab", analyze_all_ncaab_games, sportsbook),
        safe_analyze("college-baseball", analyze_all_college_baseball_games, sportsbook),
        safe_analyze("cfb", analyze_all_cfb_games, sportsbook),
        safe_analyze("mlb", analyze_all_mlb_games, sportsbook)
    ]
    
    results = await asyncio.gather(*tasks)
    
    # Aggregate stats
    total_games = sum(r.get("count", 0) for r in results)
    total_value_bets = sum(r.get("value_bets_found", 0) for r in results)
    
    final_result = {
        "timestamp": datetime.now().isoformat(),
        "sportsbook": sportsbook,
        "total_games": total_games,
        "total_value_bets": total_value_bets,
        "results_by_sport": {r["sport"]: r for r in results},
        # Flattened games list for easier frontend display in a single table
        "all_games": [
            {**game, "sport_key": r["sport"]} 
            for r in results 
            for game in r.get("games", [])
        ]
    }

    # Save Snapshot
    try:
        from src.odds_cache import get_cache_service
        cache = get_cache_service()
        # Ensure tables exist (lazy init)
        await cache.ensure_table()
        await cache.save_snapshot({**final_result, "sport": "all"})
    except Exception as e:
        logger.error(f"Failed to save historical snapshot: {e}")

    return sanitize_for_json(final_result)
