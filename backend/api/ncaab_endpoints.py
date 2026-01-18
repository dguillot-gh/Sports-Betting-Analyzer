from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import pandas as pd
from datetime import datetime
import logging

# Import predictor to reuse data loading logic
# Assuming scripts is in path or relative import
try:
    from scripts.ncaab_predictor import NCAABPredictor
    from scripts.train_ncaab_model import train_v2 as train_ncaab
except ImportError:
    # Fallback for different path structures
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.ncaab_predictor import NCAABPredictor
    from scripts.train_ncaab_model import train_v2 as train_ncaab

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trends/ncaab", tags=["NCAAB Trends"])


@router.post("/train")
async def train_model(background_tasks: BackgroundTasks):
    """
    Trigger retraining of the NCAAB XGBoost model.
    Runs in the background.
    """
    try:
        background_tasks.add_task(train_ncaab)
        return {"status": "accepted", "message": "NCAAB model training started in background."}
    except Exception as e:
        logger.error(f"Error starting NCAAB training: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/backtest")
async def run_backtest_endpoint():
    """
    Run a quick backtest on recent data and return the report.
    For this version, we run it synchronously as it's fast (~1-2s for 1 season).
    """
    try:
        from scripts.backtest_ncaab import run_backtest
        report = run_backtest(season_filter=True)
        return report
    except Exception as e:
        logger.error(f"Error running backtest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class HitRateResult(BaseModel):
    team: str
    metric: str
    line: float
    games_analyzed: int
    hits: int
    hit_rate: float
    avg_value: float
    game_log: List[Dict[str, Any]]

@router.get("/hit-rate", response_model=HitRateResult)
async def get_team_hit_rate(
    team: str,
    metric: str = Query(..., description="Metric to analyze: 'total', 'team_score', 'margin'"),
    line: float = Query(..., description="Betting line to test against"),
    last_n: int = Query(10, ge=5, le=50, description="Number of recent games to analyze")
):
    """
    Calculate how often a team hits a specific line (Over/Under/Spread) in recent games.
    """
    try:
        predictor = NCAABPredictor()
        # Force load if not loaded
        if predictor.stats_df is None:
            predictor._load_data()
            
        if predictor.stats_df is None or predictor.stats_df.empty:
             raise HTTPException(status_code=404, detail="NCAAB data not available")

        # Normalize team name matching (reuse predictor logic or simple contains)
        df = predictor.stats_df
        
        # Simple case-insensitive match for now (can be improved)
        team_df = df[df['team_display_name'].str.contains(team, case=False, na=False)]
        
        if team_df.empty:
            raise HTTPException(status_code=404, detail=f"Team '{team}' not found")
            
        # Sort by date descending (assuming season/date columns or just use recent)
        # The parquet has 'season' but maybe not exact date? 
        # hoopR boxscores usually have 'game_date'. Let's check columns if feasible, but for now generic sort.
        if 'game_date' in team_df.columns:
            team_df = team_df.sort_values('game_date', ascending=False)
        else:
            # Fallback: sort by season desc, then maybe just take top?
            # Assuming file order is roughly chronological or reverse
            team_df = team_df.sort_values('season', ascending=False)

        # Take last N
        recent_games = team_df.head(last_n).copy()
        
        hits = 0
        total_value = 0.0
        game_log = []
        
        for _, row in recent_games.iterrows():
            actual_value = 0.0
            is_hit = False
            
            # Extract scores
            team_score = float(row.get('team_score', 0))
            opp_score = float(row.get('opponent_team_score', 0))
            
            if metric == 'total':
                actual_value = team_score + opp_score
                is_hit = actual_value > line # 'Over' logic by default
            elif metric == 'team_score':
                actual_value = team_score
                is_hit = actual_value > line
            elif metric == 'margin':
                # Spread hit: (Team - Opp) > (-Spread) ? 
                # Be careful with spread sign. Usually "Cover -5" means Win by >5.
                # If user inputs line "-5.5", they want to know if team covered -5.5.
                # Actual margin > Line
                actual_value = team_score - opp_score
                is_hit = actual_value > line
                
            if is_hit:
                hits += 1
            
            total_value += actual_value
            
            game_log.append({
                "date": str(row.get('game_date', 'N/A')),
                "opponent": row.get('opponent_name', 'Unknown'), # hoopR usually has this? Or derived.
                "score": f"{int(team_score)}-{int(opp_score)}",
                "value": actual_value,
                "is_hit": is_hit
            })
            
        return {
            "team": team,
            "metric": metric,
            "line": line,
            "games_analyzed": len(recent_games),
            "hits": hits,
            "hit_rate": hits / len(recent_games) if len(recent_games) > 0 else 0,
            "avg_value": round(total_value / len(recent_games), 1) if len(recent_games) > 0 else 0,
            "game_log": game_log
        }

    except Exception as e:
        print(f"Error calculating hit rate: {e}")
        raise HTTPException(status_code=500, detail=str(e))
