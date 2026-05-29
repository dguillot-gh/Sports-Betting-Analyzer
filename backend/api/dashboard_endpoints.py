
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Dict, Any, List
import json
import os
from pathlib import Path
import logging
from datetime import datetime
from api.json_utils import sanitize_for_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

REPO_ROOT = Path(__file__).parent.parent


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_primary_model(game: Dict[str, Any]) -> Dict[str, Any]:
    """
    Use xgboost model when available, otherwise fallback to simple model.
    Endpoints currently include both for NBA/NFL analyze-all responses.
    """
    xgb_model = game.get("xgboost_model")
    if isinstance(xgb_model, dict) and not xgb_model.get("error"):
        return xgb_model

    simple_model = game.get("simple_model")
    if isinstance(simple_model, dict):
        return simple_model

    return game


def _build_top_pick(game: Dict[str, Any], sport: str) -> Dict[str, Any]:
    model = _extract_primary_model(game)
    home_team = game.get("home_team") or ""
    away_team = game.get("away_team") or ""

    home_prob = _safe_float(model.get("home_win_probability"), 0.5)
    predicted_winner = model.get("predicted_winner")
    if not predicted_winner:
        predicted_winner = home_team if home_prob >= 0.5 else away_team

    edge_pct = _safe_float(model.get("home_ml_edge"), 0.0)
    if predicted_winner == away_team:
        edge_pct = -edge_pct
    edge_abs_pct = abs(edge_pct)

    value_score = round(min(edge_abs_pct * 1.7, 99.0), 1)

    if predicted_winner == home_team:
        probability = home_prob
    else:
        probability = 1.0 - home_prob

    return {
        "sport": sport.upper(),
        "home_team": home_team,
        "away_team": away_team,
        "game_time": game.get("game_time") or "",
        "winner": f"{predicted_winner} ML",
        "probability": round(probability, 3),
        "edge": round(edge_abs_pct / 100.0, 4),
        "value_score": value_score
    }

@router.get("/model-summary")
async def get_model_summary(request: Request):
    """
    Scans the models/ directory and returns an aggregated summary of all 
    trained models and their metrics.
    """
    try:
        models_base = REPO_ROOT / "models"
        if not models_base.exists():
            return []

        summary = []
        
        # We want to find all *_metrics.json files
        # They are usually at models/{sport}/{task}/... or models/{sport}/{series}/{task}/...
        for metrics_path in models_base.rglob("*_metrics.json"):
            try:
                # Relative path to models/
                rel_path = metrics_path.relative_to(models_base)
                parts = rel_path.parts
                
                # Part structure varies: 
                # e.g. nba/default/classification_metrics.json -> parts = (nba, default, classification_metrics.json)
                # e.g. nascar/cup/race_win/classification_metrics.json -> (nascar, cup, race_win, classification_metrics.json)
                
                if len(parts) < 2: continue
                
                sport = parts[0]
                task = parts[-2] # The directory containing the metrics file is usually the task name
                series = "/".join(parts[1:-2]) if len(parts) > 3 else parts[1]
                
                with open(metrics_path, "r") as f:
                    metrics = json.load(f)
                
                # Extract interesting metrics
                accuracy = metrics.get("accuracy", metrics.get("val_accuracy", 0))
                precision = metrics.get("precision", 0)
                roi = metrics.get("roi", 0) # Non-standard but good to have
                
                # Use mean if it's a list (some metrics are recorded per epoch)
                if isinstance(accuracy, list) and accuracy: accuracy = accuracy[-1]
                
                summary.append({
                    "sport": sport,
                    "series": series,
                    "task": task,
                    "accuracy": round(accuracy, 3) if accuracy else 0,
                    "precision": round(precision, 3) if precision else 0,
                    "roi": round(roi, 1) if roi else 0,
                    "last_updated": os.path.getmtime(metrics_path)
                })
            except Exception as e:
                logger.warning(f"Error parsing metrics at {metrics_path}: {e}")

        # Sort by accuracy descending
        summary.sort(key=lambda x: x["accuracy"], reverse=True)
        
        return summary
    except Exception as e:
        logger.error(f"Dashboard summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-picks")
async def get_top_picks(
    sportsbook: str = Query("draftkings", description="Sportsbook to fetch odds from"),
    limit: int = Query(8, ge=1, le=30, description="Maximum number of picks to return"),
):
    """
    Build dashboard-ready top picks from ALL live sports (NBA, NFL, MLB, NHL, NCAAB, CFB, College Baseball).
    """
    import asyncio

    try:
        from scripts.nba_odds import get_todays_nba_odds
        from scripts.nba_predictor import analyze_matchup_dual
        from scripts.nfl_predictor import get_todays_nfl_odds, analyze_nfl_matchup_dual

        picks: List[Dict[str, Any]] = []

        async def collect_for_sport(
            sport: str,
            odds_loader,
            analyzer,
        ) -> None:
            try:
                odds_data = await odds_loader(sportsbook)
                games = odds_data.get("games", []) if isinstance(odds_data, dict) else []

                for game in games:
                    home = game.get("home_team")
                    away = game.get("away_team")
                    if not home or not away:
                        continue

                    try:
                        analyzed = await analyzer(
                            home_team=home,
                            away_team=away,
                            spread=game.get("spread"),
                            over_under=game.get("over_under"),
                            home_ml=game.get("home_moneyline"),
                            away_ml=game.get("away_moneyline"),
                        )
                        merged = {**game, **(analyzed or {})}
                        picks.append(_build_top_pick(merged, sport))
                    except Exception as inner_exc:
                        logger.warning("Failed to analyze %s game %s vs %s: %s", sport, away, home, inner_exc)
            except Exception as sport_exc:
                logger.warning("Failed to collect %s top picks: %s", sport, sport_exc)

        async def collect_from_analyze_all(sport: str, analyze_all_fn) -> None:
            """Collect picks from sports that use an analyze-all endpoint."""
            try:
                result = await analyze_all_fn(sportsbook=sportsbook)
                if isinstance(result, dict):
                    games = result.get("games", [])
                elif hasattr(result, "body"):
                    import json as _json
                    games = _json.loads(result.body).get("games", [])
                else:
                    games = []
                for game in games:
                    if game.get("error") or game.get("prediction_error"):
                        continue
                    try:
                        picks.append(_build_top_pick(game, sport))
                    except Exception as inner_exc:
                        logger.warning("Failed to build %s pick: %s", sport, inner_exc)
            except Exception as sport_exc:
                logger.warning("Failed to collect %s top picks: %s", sport, sport_exc)

        # Tier 1: NBA & NFL (direct odds+analyzer pattern)
        # Tier 2: MLB, NHL (direct odds+analyzer pattern — same signature)
        # Tier 3: NCAAB, CFB, College Baseball (use their analyze-all endpoints)
        from scripts.mlb_odds import get_todays_mlb_odds
        from scripts.mlb_predictor import analyze_mlb_matchup
        from scripts.nhl_odds import get_todays_nhl_odds
        from scripts.nhl_predictor import analyze_nhl_matchup
        from api.odds_endpoints import (
            analyze_all_ncaab_games,
            analyze_all_cfb_games,
            analyze_all_college_baseball_games,
        )

        await asyncio.gather(
            collect_for_sport("nba", get_todays_nba_odds, analyze_matchup_dual),
            collect_for_sport("nfl", get_todays_nfl_odds, analyze_nfl_matchup_dual),
            collect_for_sport("mlb", get_todays_mlb_odds, analyze_mlb_matchup),
            collect_for_sport("nhl", get_todays_nhl_odds, analyze_nhl_matchup),
            collect_from_analyze_all("ncaab", analyze_all_ncaab_games),
            collect_from_analyze_all("cfb", analyze_all_cfb_games),
            collect_from_analyze_all("college-baseball", analyze_all_college_baseball_games),
        )

        picks.sort(key=lambda item: item.get("value_score", 0), reverse=True)
        sliced = picks[:limit]

        return sanitize_for_json({
            "date": datetime.utcnow().isoformat(),
            "sportsbook": sportsbook,
            "count": len(sliced),
            "picks": sliced
        })
    except Exception as exc:
        logger.error("Dashboard top picks error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to build top picks")
