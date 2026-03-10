# api/app.py
import src.patch_xgboost  # Monkeypatch for legacy sportsdataverse models
from pathlib import Path
import sys
import json
import os
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime

# Monkeypatch for Python 3.13 compatibility
import collections
import collections.abc
for name in ['MutableSet', 'MutableMapping', 'Mapping', 'Iterable', 'Callable', 'Sequence']:
    if not hasattr(collections, name):
        setattr(collections, name, getattr(collections.abc, name))

from api.log_capture import setup_log_capture, get_logs, LOG_BUFFER
from api.db_endpoints import router as db_router, import_status, run_ncaab_import
from api.odds_endpoints import router as odds_router
from api.results_endpoints import router as results_router
from api.backtest_endpoints import router as backtest_router
from api.player_stats_endpoints import router as player_stats_router
from api.cache_endpoints import router as cache_router
from api.bet_tracker_endpoints import router as bet_tracker_router
from api.model_lab_endpoints import router as model_lab_router
from api.nascar_endpoints import router as nascar_router
from api.espn_endpoints import router as espn_router
from api.bug_tracker_endpoints import router as bug_tracker_router
from api.dashboard_endpoints import router as dashboard_router
from api.ai_endpoints import router as ai_router
from api.ncaab_endpoints import router as ncaab_router
from api.scheduler_endpoints import router as scheduler_router
from api.analysis_cache_endpoints import router as analysis_cache_router
from api.cfb_endpoints import router as cfb_router
from api.nascar_live_endpoints import router as nascar_live_router
from api.nhl_endpoints import router as nhl_router
from api.expert_picks_endpoints import router as expert_picks_router
from api.baseball_endpoints import router as baseball_router
from api.deployment_endpoints import router as deployment_router
from fastapi import FastAPI, HTTPException, UploadFile, File, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
# import pandas as pd  <-- Moved to local function scope
# import joblib     <-- Moved to local function scope
import yaml
import logging

# Make repo modules importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT)) # Add backend root
sys.path.insert(0, str(REPO_ROOT / 'src'))

from data_loader import load_sport_data
import train as train_mod
import nascar_enhancer
from sport_factory import SportFactory
from simulation import SimulationEngine
from dataset_manager import DatasetManager

# Use the new data updaters
from data_sources import NASCARDataUpdater, NFLDataUpdater, GitHubDataSource, BaseDataUpdater
from services.scheduler import SchedulerService

# Import version management (full semantic versioning)
from src.version import get_version, get_version_info

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get version
current_version = get_version()
app = FastAPI(title='Sports ML API', version=current_version)

setup_log_capture()  # Enable log capture for /logs endpoint
app.include_router(db_router)  # Database endpoints
app.include_router(odds_router)  # Live odds endpoints
app.include_router(results_router)  # Game results for syncing
app.include_router(backtest_router)  # Backtesting endpoints
app.include_router(player_stats_router)  # Player stats and hit rates
app.include_router(cache_router)  # Odds caching for late night games
app.include_router(bet_tracker_router)  # Bet tracking
app.include_router(model_lab_router)  # Model Lab testing sandbox
app.include_router(nascar_router)  # NASCAR live data & schedule
app.include_router(espn_router)  # ESPN BPI/FPI predictions
app.include_router(bug_tracker_router)  # Bug tracking
app.include_router(dashboard_router)  # Dashboard metrics summary
app.include_router(ai_router)  # Unified AI Advisor (Multi-engine + LLM)
app.include_router(ncaab_router)  # NCAAB Trends
app.include_router(scheduler_router)  # Import Scheduler & Logs
app.include_router(analysis_cache_router) # Manual Analysis Cache
app.include_router(cfb_router)  # College Football Data
app.include_router(nascar_live_router)  # NASCAR Live Dashboard Logic
app.include_router(nhl_router)  # NHL Data and Predictions
app.include_router(expert_picks_router)  # CBS Expert Picks scraper data
app.include_router(baseball_router)  # College Baseball Data
app.include_router(deployment_router)  # Deployment tracking

# Dev CORS. Tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

CFG_DIR = REPO_ROOT / 'configs'
MODELS_DIR = REPO_ROOT / 'models'

# Data directories
NASCAR_DATA_DIR = REPO_ROOT / 'data' / 'nascar' / 'raw'
NFL_DATA_DIR = REPO_ROOT / 'data' / 'nfl'
NBA_DATA_DIR = REPO_ROOT / 'data' / 'nba'

# Initialize Managers
DATASET_MANAGER = DatasetManager(REPO_ROOT / 'data')

# Cache helpers
from threading import Lock
MODEL_CACHE: dict[tuple[str, str, str], object] = {}
CACHE_LOCK = Lock()


def model_paths(sport: str, series_label: str, task: str) -> Path:
    # E.g., models/nascar/cup/classification_model.joblib
    return MODELS_DIR / sport / series_label / f'{task}_model.joblib'


# ---------- Health ----------
@app.get('/health')
def health():
    return {'ok': True, 'sports': ['nascar', 'nfl', 'nba'], 'version': current_version}


# ---------- Version Information ----------
@app.get('/version')
def get_version_endpoint():
    """Get version information"""
    return get_version_info()


# ---------- Schema & Prediction Endpoints ----------

@app.get('/{sport}/schema')
def get_schema(sport: str, series: Optional[str] = None):
    """
    Get feature and target schema for a sport.
    Returns categorical/numeric features and available targets.
    """
    try:
        import pandas as pd
        s, _ = SportFactory.get_sport(sport, series)
        df = load_sport_data(s)
        
        # Identify feature types
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
        
        # Common target columns for NASCAR
        targets = ['finish', 'win', 'top5', 'top10', 'result']
        available_targets = [t for t in targets if t in df.columns]
        
        return {
            'sport': sport,
            'features': {
                'numeric': [c for c in numeric_cols if c not in available_targets][:20],
                'categorical': [c for c in categorical_cols if c not in ['driver', 'team']][:15]
            },
            'targets': available_targets,
            'total_rows': len(df)
        }
    except Exception as e:
        logger.error(f"Error getting schema for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PredictRequestBody(BaseModel):
    features: Dict[str, Any] = {}


@app.post('/{sport}/predict/{task}')
def make_prediction(sport: str, task: str, request: PredictRequestBody, series: Optional[str] = None):
    """
    Make a prediction using a trained model.
    Supports classification (win/top5/top10) and regression (finish position).
    """
    try:
        import numpy as np
        from pathlib import Path
        
        features = request.features
        driver = features.get('driver', 'Unknown')
        start_pos = features.get('start', features.get('start_pos', 10))
        track_type = features.get('track_type', 'intermediate')
        
        # Simple heuristic prediction based on starting position
        # In production, this would load and use a trained ML model
        base_finish = float(start_pos) * 0.6 + np.random.uniform(-3, 3)
        base_finish = max(1, min(40, base_finish))
        
        # Win probability decreases with starting position
        win_prob = max(0.01, 0.25 - (float(start_pos) - 1) * 0.015)
        top5_prob = max(0.05, 0.6 - (float(start_pos) - 1) * 0.02)
        top10_prob = max(0.1, 0.8 - (float(start_pos) - 1) * 0.03)
        
        # Track type adjustments
        if track_type == 'superspeedway':
            win_prob *= 0.7  # More unpredictable
            top5_prob *= 0.8
        
        predictions = {
            'driver': driver,
            'predicted_finish': round(base_finish, 1),
            'win_probability': round(win_prob * 100, 1),
            'top5_probability': round(top5_prob * 100, 1),
            'top10_probability': round(top10_prob * 100, 1),
            'confidence': 'Medium' if start_pos <= 10 else 'Low',
            'task': task
        }
        
        return {
            'predictions': predictions,
            'model_info': {
                'type': 'heuristic',
                'version': '1.0',
                'note': 'Based on historical starting position patterns'
            }
        }
    except Exception as e:
        logger.error(f"Error predicting for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/{sport}/feature_values')
def get_feature_values(sport: str, series: Optional[str] = None):
    """
    Get unique values for categorical features (for dropdowns).
    """
    try:
        s, _ = SportFactory.get_sport(sport, series)
        df = load_sport_data(s)
        
        result = {}
        categorical_cols = ['driver', 'team', 'track', 'track_type', 'manufacturer']
        
        for col in categorical_cols:
            if col in df.columns:
                unique_values = df[col].dropna().unique().tolist()
                # Limit to top 100 values, sorted
                unique_values = sorted(unique_values[:100])
                result[col] = unique_values
        
        return result
    except Exception as e:
        logger.error(f"Error getting feature values for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Entity Endpoints (Profiles) ----------

@app.get('/{sport}/entities')
def get_entities(sport: str, series: Optional[str] = None):
    """
    Get list of all available entities (drivers/teams) for a sport.
    """
    try:
        s, _ = SportFactory.get_sport(sport, series)
        return s.get_entities()
    except Exception as e:
        logger.error(f"Error getting entities for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/{sport}/profile/{entity_id}')
def get_entity_profile(sport: str, entity_id: str, series: Optional[str] = None, year: Optional[int] = None):
    """
    Get comprehensive stats for a specific entity.
    """
    try:
        s, _ = SportFactory.get_sport(sport, series)
        # Decode entity_id if it contains special characters
        from urllib.parse import unquote
        entity_id = unquote(entity_id)
        
        return s.get_entity_stats(entity_id, year=year)
    except Exception as e:
        logger.error(f"Error getting profile for {sport} {entity_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/{sport}/teams')
def get_teams(sport: str, series: Optional[str] = None):
    """
    Get list of all available teams for a sport.
    """
    try:
        s, _ = SportFactory.get_sport(sport, series)
        return s.get_teams()
    except Exception as e:
        logger.error(f"Error getting teams for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/{sport}/drivers')
def get_drivers(sport: str, series: Optional[str] = None, team: Optional[str] = None):
    """Get list of drivers/players for a sport, optionally filtered by team."""
    try:
        s, _ = SportFactory.get_sport(sport, series)
        return s.get_drivers(team)
    except Exception as e:
        logger.error(f"Error getting drivers for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/{sport}/data')
def get_data(sport: str, series: Optional[str] = None, limit: int = 100, skip: int = 0,
             season_min: Optional[int] = None, season_max: Optional[int] = None,
             track_type: Optional[str] = None, driver: Optional[str] = None):
    try:
        import pandas as pd
        s, _ = SportFactory.get_sport(sport, series)
        df = load_sport_data(s)
        
        # Generic filtering based on common column names
        # 'year' or 'schedule_season' for season filtering
        season_col = None
        if 'year' in df.columns:
            season_col = 'year'
        elif 'schedule_season' in df.columns:
            season_col = 'schedule_season'
            
        if season_col:
            if season_min is not None:
                df = df[df[season_col] >= season_min]
            if season_max is not None:
                df = df[df[season_col] <= season_max]
        
        if track_type and 'track_type' in df.columns:
            df = df[df['track_type'] == track_type]
            
        if driver and 'driver' in df.columns:
            # Case-insensitive partial match
            df = df[df['driver'].str.contains(driver, case=False, na=False)]
        
        # Calculate total rows after filtering
        total_rows = len(df)
        
        # Apply pagination
        out = df.iloc[skip : skip + limit]
        
        # Fix NaN values before JSON serialization
        out = out.replace({pd.NA: None, float('nan'): None})
        
        return {'columns': out.columns.tolist(), 'rows': out.to_dict(orient='records'), 'total_rows': total_rows}
        
    except Exception as e:
        logger.error(f"Error getting data for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TrainPayload(BaseModel):
    hyperparameters: Optional[Dict[str, Any]] = None


@app.post('/{sport}/train/{task}')
def train_model(sport: str, task: str, payload: Optional[TrainPayload] = None, train_start: Optional[int] = None, test_start: Optional[int] = None, series: Optional[str] = None):
    if task not in ('classification', 'regression'):
        raise HTTPException(status_code=400, detail='task must be classification or regression')

    try:
        s, label = SportFactory.get_sport(sport, series)
        
        hyperparams = payload.hyperparameters if payload else None
        
        # Determine output directory
        out_dir = MODELS_DIR / sport / label
        out_dir.mkdir(parents=True, exist_ok=True)

        # Check if sport has multiple classification targets (e.g., NASCAR)
        target_config = s.get_target_columns()
        classification_targets = target_config.get('classification', None)
        
        # If classification is a list and task is classification, train all targets
        if task == 'classification' and isinstance(classification_targets, list):
            results = {}
            all_metrics = {}
            
            for target_name in classification_targets:
                # Create target-specific output directory
                target_out_dir = out_dir / target_name
                target_out_dir.mkdir(parents=True, exist_ok=True)
                
                # Temporarily override the target column for training
                original_method = s.get_target_columns
                s.get_target_columns = lambda t=target_name: {'classification': t, 'regression': target_config.get('regression', 'finishing_position')}
                
                try:
                    model_path, metrics_path, metrics = train_mod.train_and_evaluate_sport(
                        s, task, 
                        out_dir=target_out_dir,
                        test_start_season=test_start,
                        train_start_season=train_start,
                        hyperparameters=hyperparams
                    )
                    
                    results[target_name] = {
                        "model_path": str(model_path),
                        "metrics_path": str(metrics_path)
                    }
                    all_metrics[target_name] = metrics
                    
                    # Clear cache
                    key = (sport, label, f"{task}_{target_name}")
                    with CACHE_LOCK:
                        if key in MODEL_CACHE:
                            del MODEL_CACHE[key]
                            
                finally:
                    s.get_target_columns = original_method
            
            return {
                "status": "success",
                "multi_target": True,
                "targets_trained": list(classification_targets),
                "results": results,
                "metrics": all_metrics
            }
        
        # Standard single-target training
        model_path, metrics_path, metrics = train_mod.train_and_evaluate_sport(
            s, task, 
            out_dir=out_dir,
            test_start_season=test_start,
            train_start_season=train_start,
            hyperparameters=hyperparams
        )
        
        # Clear cache
        key = (sport, label, task)
        with CACHE_LOCK:
            if key in MODEL_CACHE:
                del MODEL_CACHE[key]
        
        return {
            "status": "success",
            "model_path": str(model_path),
            "metrics_path": str(metrics_path),
            "metrics": metrics
        }
    except Exception as e:
        logger.error(f"Error training model for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/{sport}/predict/{task}')
def predict(sport: str, task: str, payload: dict, series: Optional[str] = None):
    if task not in ('classification', 'regression'):
        raise HTTPException(status_code=400, detail='task must be classification or regression')

    try:
        s, label = SportFactory.get_sport(sport, series)
        
        # Check cache first
        key = (sport, label, task)
        model = None
        with CACHE_LOCK:
            model = MODEL_CACHE.get(key)
            
        if model is None:
            import joblib
            path = model_paths(sport, label, task)
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"No trained {task} model for {sport} series '{label}'. Train first.")
            model = joblib.load(path)
            # Cache it
            with CACHE_LOCK:
                MODEL_CACHE[key] = model

        feats = s.get_feature_columns()
        cols = feats.get('categorical', []) + feats.get('boolean', []) + feats.get('numeric', [])

        # Handle nested features key from C# PredictRequest
        features = payload.get('features', payload)
        row = {c: features.get(c, None) for c in cols}
        
        import pandas as pd
        X = pd.DataFrame([row], columns=cols)

        pred = model.predict(X)[0]
        resp = {'series': label, 'prediction': float(pred) if task == 'regression' else int(pred)}
        
        # Add probability and confidence for classification
        if task == 'classification':
            try:
                if hasattr(model, 'predict_proba'):
                    proba_all = model.predict_proba(X)[0]
                    
                    # For binary classification, use probability of predicted class
                    if len(proba_all) == 2:
                        proba = proba_all[1] if pred == 1 else proba_all[0]
                    else:
                        # Multi-class: use probability of predicted class
                        proba = proba_all[int(pred)] if int(pred) < len(proba_all) else max(proba_all)
                    
                    resp['probability'] = float(proba)
                    resp['confidence_percent'] = int(proba * 100)
                    
                    # Categorize confidence level
                    if proba >= 0.70:
                        resp['confidence'] = 'high'
                    elif proba >= 0.50:
                        resp['confidence'] = 'medium'
                    else:
                        resp['confidence'] = 'low'
            except Exception as e:
                logger.debug(f"Could not get probability: {e}")
        
        return resp
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error predicting for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/{sport}/predict/batch/{task}')
async def predict_batch(sport: str, task: str, series: Optional[str] = None, file: UploadFile = File(...)):
    """
    Batch prediction from CSV file.
    """
    if task not in ('classification', 'regression'):
        raise HTTPException(status_code=400, detail='task must be classification or regression')

    try:
        s, label = SportFactory.get_sport(sport, series)
        model_dir = MODELS_DIR / sport / label
        model_path = model_dir / f'{task}_model.joblib'
        
        if not model_path.exists():
            raise HTTPException(status_code=404, detail=f'No trained {task} model found. Train first.')

        try:
            import joblib
            model = joblib.load(model_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'Failed to load model: {e}')

        # Read CSV
        try:
            import pandas as pd
            df = pd.read_csv(file.file)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f'Invalid CSV file: {e}')

        # Prepare features
        feats = s.get_feature_columns()
        cols = feats.get('categorical', []) + feats.get('boolean', []) + feats.get('numeric', [])
        
        # Ensure all columns exist (fill missing with None/NaN)
        for col in cols:
            if col not in df.columns:
                df[col] = None

        # Select only relevant columns for prediction
        X = df[cols]

        # Predict
        preds = model.predict(X)
        
        results = []
        probs = None
        if task == 'classification':
            try:
                probs = model.predict_proba(X)[:, 1]
            except Exception:
                pass

        for i, pred in enumerate(preds):
            import pandas as pd
            row_result = df.iloc[i].to_dict()
            # Clean up NaN values for JSON
            row_result = {k: (None if pd.isna(v) else v) for k, v in row_result.items()}
            
            row_result['prediction'] = float(pred) if task == 'regression' else int(pred)
            if probs is not None:
                row_result['probability'] = float(probs[i])
            
            results.append(row_result)

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail=f'Prediction failed: {e}')


@app.get('/{sport}/features/values')
def get_feature_values(sport: str, series: Optional[str] = None):
    """
    Get unique values for categorical features to populate UI dropdowns.
    """
    try:
        import pandas as pd
        s, _ = SportFactory.get_sport(sport, series)

        # Load data to get unique values
        df = load_sport_data(s)
        
        feats = s.get_feature_columns()
        categorical = feats.get('categorical', [])
        
        # Always include UI filter fields
        filter_fields = ['year', 'track_type', 'driver']
        cols_to_fetch = list(set(categorical + filter_fields))
        
        values = {}
        for col in cols_to_fetch:
            if col in df.columns:
                # Get unique values, sort them, and convert to list
                unique_vals = sorted(df[col].dropna().unique().tolist())
                values[col] = unique_vals
            else:
                values[col] = []
                
        return values

    except Exception as e:
        logger.error(f"Error getting feature values: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/{sport}/mappings/drivers')
def get_driver_mappings(sport: str, series: Optional[str] = None):
    """
    Get mapping of drivers to their most recent/frequent team and manufacturer.
    """
    try:
        import pandas as pd
        s, _ = SportFactory.get_sport(sport, series)
        df = load_sport_data(s)
        
        if 'driver' not in df.columns:
            return {}

        # relevant columns to map
        targets = ['manu', 'team_name']
        available_targets = [c for c in targets if c in df.columns]
        
        if not available_targets:
            return {}

        # Sort by season/race to get latest info
        sort_cols = []
        if 'schedule_season' in df.columns: sort_cols.append('schedule_season')
        if 'year' in df.columns: sort_cols.append('year')
        if 'race_num' in df.columns: sort_cols.append('race_num')
        
        if sort_cols:
            df = df.sort_values(sort_cols, ascending=True)

        mappings = {}
        
        # Group by driver and take the last non-null value for each target
        # This assumes the dataset is sorted chronologically
        for driver, group in df.groupby('driver'):
            driver_map = {}
            for target in available_targets:
                # Get last valid value
                vals = group[target].dropna()
                if not vals.empty:
                    driver_map[target] = vals.iloc[-1]
            
            if driver_map:
                mappings[driver] = driver_map

        return mappings

    except Exception as e:
        logger.error(f"Error getting driver mappings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/{sport}/models")
async def get_models(sport: str):
    """
    Get list of trained models and their metrics.
    """
    try:
        models_dir = REPO_ROOT / 'models' / sport
        if not models_dir.exists():
            return []

        models = []
        
        # Helper to process a directory
        def process_dir(directory: Path, series_name: str):
            for metrics_file in directory.glob("*_metrics.json"):
                try:
                    with open(metrics_file, 'r') as f:
                        metrics = json.load(f)
                    
                    task_name = metrics_file.name.replace("_metrics.json", "")
                    
                    models.append({
                        "sport": sport,
                        "series": series_name,
                        "task": task_name,
                        "metrics": metrics,
                        "last_updated": metrics_file.stat().st_mtime
                    })
                except Exception as e:
                    logger.warning(f"Error reading metrics file {metrics_file}: {e}")

        # 1. Scan root directory (e.g. models/nfl/)
        # Models here get the series name "default" (or just use sport name if preferred)
        process_dir(models_dir, "default")

        # 2. Scan subdirectories (e.g. models/nascar/cup/)
        if models_dir.exists():
            for series_dir in models_dir.iterdir():
                if series_dir.is_dir():
                    process_dir(series_dir, series_dir.name)
                    
                    # 3. Scan target subdirectories for multi-target training (e.g. models/nascar/cup/race_win/)
                    for target_dir in series_dir.iterdir():
                        if target_dir.is_dir():
                            # Use series/target as the series name for display
                            process_dir(target_dir, f"{series_dir.name}/{target_dir.name}")
        
        return models
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/{sport}/models/{series}/{task}")
def delete_model(sport: str, series: str, task: str):
    """
    Delete a trained model and its metrics.
    """
    try:
        # Construct paths
        # series is the label used in directory structure
        model_dir = MODELS_DIR / sport / series
        model_path = model_dir / f'{task}_model.joblib'
        metrics_path = model_dir / f'{task}_metrics.json'

        deleted = False
        
        if model_path.exists():
            model_path.unlink()
            deleted = True
            
        if metrics_path.exists():
            metrics_path.unlink()
            deleted = True
            
        # Remove from cache
        key = (sport, series, task)
        with CACHE_LOCK:
            if key in MODEL_CACHE:
                del MODEL_CACHE[key]
                
        if not deleted:
            raise HTTPException(status_code=404, detail="Model not found")
            
        return {"status": "success", "message": f"Deleted {sport}/{series}/{task} model"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/{sport}/enhance')
def enhance_data(sport: str):
    """
    Trigger data enhancement process for a sport.
    """
    try:
        if sport == 'nascar':
            results = nascar_enhancer.enhance_all_series(REPO_ROOT / 'data' / 'nascar')
            return {
                "success": True,
                "message": f"Enhanced {len(results.get('series_results', {}))} series",
                "series_enhanced": list(results.get('series_results', {}).keys()),
                "details": results
            }
        else:
            raise HTTPException(status_code=400, detail=f"Enhancement not supported for {sport}")
    except Exception as e:
        logger.error(f"Error enhancing data for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SimulationRequest(BaseModel):
    drivers: List[str]
    year: int
    track_type: str = "Intermediate"
    num_simulations: int = 1000


@app.post('/{sport}/simulate')
def simulate_race(sport: str, payload: SimulationRequest, series: Optional[str] = None):
    """
    Run Monte Carlo simulation for a race.
    """
    try:
        if sport != 'nascar':
             raise HTTPException(status_code=400, detail="Simulation only supported for NASCAR")
             
        s, _ = SportFactory.get_sport(sport, series)
        engine = SimulationEngine(s)
        
        results = engine.run_monte_carlo(
            drivers=payload.drivers,
            year=payload.year,
            track_type=payload.track_type,
            num_simulations=payload.num_simulations
        )
        return results
    except Exception as e:
        logger.error(f"Error running simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class NFLSeasonSimRequest(BaseModel):
    simulations: int = 1000
    force_refresh: bool = False


@app.post('/simulation/nfl/season')
async def simulate_nfl_season(payload: Optional[NFLSeasonSimRequest] = None):
    """
    Run NFL season simulation using nflseedR.
    Returns playoff probabilities, Super Bowl odds, and draft order.
    Results are cached for 6 hours.
    """
    try:
        from scripts.nfl_season_simulator import run_nfl_simulation, get_cached_simulation
        
        # Check cache if not forcing refresh
        if payload and not payload.force_refresh:
            cached = get_cached_simulation()
            if cached and cached.get("cached"):
                return cached

        if payload:
            results = await run_nfl_simulation(
                n_simulations=payload.simulations,
                force_refresh=payload.force_refresh
            )
        else:
            results = await run_nfl_simulation()
        
        return results
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return {
            "error": True,
            "message": "NFL season simulator module not available",
            "detail": str(e)
        }
    except Exception as e:
        logger.error(f"Error running NFL simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/simulation/nfl/status')
def get_nfl_simulation_status():
    """Get current status of running NFL simulation."""
    from scripts.nfl_season_simulator import get_simulation_status
    return get_simulation_status()


@app.get('/simulation/nfl/season')
async def get_nfl_simulation():
    """
    Get cached NFL season simulation results.
    """
    try:
        from scripts.nfl_season_simulator import get_cached_simulation
        
        results = get_cached_simulation()
        if results:
            return results
        else:
            return {
                "error": True,
                "message": "No cached results. Run POST /simulation/nfl/season first."
            }
    except Exception as e:
        logger.error(f"Error getting NFL simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class NASCARSeasonSimRequest(BaseModel):
    series: str = "cup"  # cup, xfinity, trucks
    simulations: int = 100
    drivers: Optional[List[str]] = None


@app.post('/simulation/nascar/season')
async def simulate_nascar_season(payload: Optional[NASCARSeasonSimRequest] = None):
    """
    Run NASCAR season simulation.
    Simulates full season with playoffs and championship.
    Returns championship probabilities, playoff odds.
    """
    try:
        from scripts.nascar_season_simulator import run_nascar_season_simulation
        
        series = payload.series if payload else "cup"
        simulations = payload.simulations if payload else 100
        drivers = payload.drivers if payload else None
        
        results = await run_nascar_season_simulation(
            series=series,
            num_simulations=simulations,
            custom_drivers=drivers
        )
        
        return results
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return {
            "error": True,
            "message": "NASCAR season simulator module not available",
            "detail": str(e)
        }
    except Exception as e:
        logger.error(f"Error running NASCAR simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/simulation/nascar/season/drivers')
async def get_nascar_season_drivers(series: str = "cup"):
    """
    Get default driver list for NASCAR season simulation.
    """
    try:
        from scripts.nascar_season_simulator import DEFAULT_DRIVERS
        return {
            "series": series,
            "drivers": DEFAULT_DRIVERS.get(series.lower(), DEFAULT_DRIVERS["cup"])
        }
    except Exception as e:
        logger.error(f"Error getting drivers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RacePredictionRequest(BaseModel):
    series: str = "cup"
    race_num: int = 1
    track_type: str = "Intermediate"
    simulations: int = 500


@app.post('/simulation/nascar/race')
async def simulate_nascar_race(payload: RacePredictionRequest):
    """
    Simulate a single NASCAR race.
    Returns win/top5/top10 probabilities for each driver.
    Great for betting predictions!
    """
    try:
        from scripts.nascar_season_simulator import NASCARSeasonSimulator, get_drivers_from_data
        
        drivers = await get_drivers_from_data(payload.series)
        simulator = NASCARSeasonSimulator(drivers, payload.series)
        
        result = simulator.simulate_single_race(
            payload.race_num,
            payload.track_type,
            payload.simulations
        )
        
        return result
    except Exception as e:
        logger.error(f"Error simulating race: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/simulation/nascar/races')
async def get_all_race_predictions(series: str = "cup", simulations: int = 200):
    """
    Get predictions for ALL races in the season.
    Returns win/top5/top10 probabilities for each race.
    """
    try:
        from scripts.nascar_season_simulator import NASCARSeasonSimulator, get_drivers_from_data
        
        drivers = await get_drivers_from_data(series)
        simulator = NASCARSeasonSimulator(drivers, series)
        
        result = simulator.simulate_all_races(simulations)
        return result
    except Exception as e:
        logger.error(f"Error getting race predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/simulation/nascar/schedule')
async def get_nascar_schedule(series: str = "cup"):
    """
    Get NASCAR schedule for the current season.
    """
    try:
        from scripts.nascar_schedule import get_schedule, get_next_race
        
        schedule = get_schedule(series)
        next_race = get_next_race(series)
        
        return {
            "series": series.upper(),
            "total_races": len(schedule),
            "next_race": next_race,
            "schedule": schedule
        }
    except Exception as e:
        logger.error(f"Error getting schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/simulation/nascar/season/predictions')
async def get_full_season_predictions(series: str = "cup", simulations: int = 300):
    """
    Get predictions for EVERY race in the season.
    Returns winner, top 5, top 10 probabilities for each race.
    Perfect for season-long betting analysis.
    """
    try:
        from scripts.nascar_schedule import get_schedule
        from scripts.nascar_season_simulator import NASCARSeasonSimulator, get_drivers_from_data
        
        schedule = get_schedule(series)
        drivers = await get_drivers_from_data(series)
        simulator = NASCARSeasonSimulator(drivers, series)
        
        all_race_predictions = []
        
        for race_info in schedule:
            # Simulate this specific race
            race_prediction = simulator.simulate_single_race(
                race_info["race"],
                race_info["track_type"],
                simulations
            )
            
            # Merge schedule info with predictions
            race_prediction["race_name"] = race_info["name"]
            race_prediction["track"] = race_info["track"]
            race_prediction["date"] = race_info["date"]
            race_prediction["is_playoff"] = race_info.get("is_playoff", False)
            race_prediction["playoff_round"] = race_info.get("playoff_round", "")
            
            all_race_predictions.append(race_prediction)
        
        return {
            "series": series.upper(),
            "total_races": len(schedule),
            "simulations_per_race": simulations,
            "races": all_race_predictions
        }
    except Exception as e:
        logger.error(f"Error getting season predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/{sport}/upcoming")
def get_upcoming_race(sport: str):
    """
    Get upcoming race info (Mock data for now).
    """
    if sport == 'nascar':
        return {
            "track": "Daytona International Speedway",
            "year": 2025,
            "race_name": "Daytona 500",
            "drivers": [
                "Ryan Blaney", "Chase Elliott", "Denny Hamlin", "Kyle Larson", 
                "William Byron", "Christopher Bell", "Joey Logano", "Martin Truex Jr.",
                "Tyler Reddick", "Brad Keselowski", "Ross Chastain", "Chris Buescher",
                "Bubba Wallace", "Ty Gibbs", "Alex Bowman", "Kyle Busch"
            ]
        }
    else:
        return {}


# ---------- Advanced Data Management Endpoints ----------

@app.get('/data/status')
def get_data_status():
    """
    Get status of all data sources including update info.
    """
    status = {
        "nascar": {"source": "GitHub", "files": {}, "datasets": []},
        "nfl": {"source": "nflverse", "files": [], "datasets": []},
        "nba": {"source": "hoopR/stats.nba.com", "files": [], "datasets": []}
    }
    
    # 1. NASCAR
    try:
        nascar_updater = NASCARDataUpdater(NASCAR_DATA_DIR)
        status["nascar"]["files"] = nascar_updater.get_status()["files"]
        status["nascar"]["datasets"] = DATASET_MANAGER.get_datasets("nascar")
        try:
             # Basic repo check
             repo_info = nascar_updater.source.get_repo_info()
             status["nascar"]["last_commit"] = repo_info.get("last_commit")
        except:
             pass
    except Exception as e:
        logger.warning(f"Error checking NASCAR status: {e}")

    # 2. Generic Sports (NFL, NBA) via MultiDataset updater logic
    for sport in ["nfl", "nba"]:
        try:
            data_dir = REPO_ROOT / 'data' / sport
            # Get configured datasets
            datasets = DATASET_MANAGER.get_datasets(sport)
            
            # If no datasets configured but we have legacy code relying on hardcoded defaults:
            # For now return empty list, front-end will handle "add dataset" prompt or we add default on startup
            # But specific to NFL, we had loose files.
            
            files = []
            if data_dir.exists():
                for f in data_dir.glob("*.csv"):
                    stat = f.stat()
                    files.append({
                        "name": f.name, 
                        "size_bytes": stat.st_size, 
                        "modified": stat.st_mtime
                    })
            
            status[sport]["files"] = files
            status[sport]["datasets"] = datasets
        except Exception as e:
             logger.warning(f"Error checking {sport} status: {e}")

    # Models count
    for sport in ["nascar", "nfl", "nba"]:
        model_dir = MODELS_DIR / sport
        count = 0
        acc = None
        if model_dir.exists():
            count = len(list(model_dir.glob("**/*_model.joblib")))
            metrics = list(model_dir.glob("**/metrics.json"))
            if metrics:
                try:
                    acc = json.load(open(metrics[0])) .get("accuracy")
                except:
                    pass
        status[sport]["models"] = count
        status[sport]["model_accuracy"] = acc
        
    return status


# ===== Column Standardization Endpoints =====

# Import column standardizer
try:
    from column_standardizer import get_standardizer
    COLUMN_STANDARDIZER = get_standardizer()
except ImportError:
    COLUMN_STANDARDIZER = None
    logger.warning("ColumnStandardizer not available")


@app.get('/data/scan/{sport}')
def scan_columns(sport: str, series: Optional[str] = None):
    """
    Scan data columns and report mapping status.
    Returns which columns can be auto-mapped, which are unmapped,
    and which required columns are present/missing.
    """
    if COLUMN_STANDARDIZER is None:
        raise HTTPException(status_code=500, detail="ColumnStandardizer not available")
    
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            return {"sport": sport, "message": "No data available to scan"}
        
        # Get column mapping report
        report = COLUMN_STANDARDIZER.scan(df, sport)
        result = report.to_dict()
        
        # Get required columns from config
        try:
            features = s.get_feature_columns()
            required_columns = []
            for col_list in features.values():
                required_columns.extend(col_list)
            
            # Also add target columns
            targets = s.get_target_columns()
            if targets:
                required_columns.extend([t for t in targets.values() if t])
            
            # Check availability
            available_cols_lower = [c.lower() for c in df.columns]
            
            required_found = []
            required_missing = []
            
            for req_col in required_columns:
                # Check if column exists (exact or lowercase match)
                if req_col in df.columns or req_col.lower() in available_cols_lower:
                    required_found.append(req_col)
                else:
                    required_missing.append(req_col)
            
            result["required_columns"] = {
                "total": len(required_columns),
                "found": len(required_found),
                "missing": len(required_missing),
                "found_list": required_found,
                "missing_list": required_missing
            }
        except Exception as e:
            logger.warning(f"Could not get required columns for {sport}: {e}")
            result["required_columns"] = None
        
        return result
        
    except Exception as e:
        logger.error(f"Error scanning columns for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/data/standardize/{sport}')
def standardize_data(sport: str, series: Optional[str] = None, save: bool = False):
    """
    Standardize column names for a sport's data.
    Optionally save the standardized data back to disk.
    """
    if COLUMN_STANDARDIZER is None:
        raise HTTPException(status_code=500, detail="ColumnStandardizer not available")
    
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            return {"sport": sport, "message": "No data available to standardize"}
        
        standardized_df, report = COLUMN_STANDARDIZER.standardize(df, sport)
        
        result = {
            "sport": sport,
            "columns_renamed": len(report.mapped),
            "unmapped_columns": report.unmapped,
            "report": report.to_dict()
        }
        
        if save:
            # Save standardized data (implementation depends on sport loader)
            data_dir = REPO_ROOT / 'data' / sport
            output_file = data_dir / f'{sport}_standardized.csv'
            standardized_df.to_csv(output_file, index=False)
            result["saved_to"] = str(output_file)
            logger.info(f"Saved standardized data to {output_file}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error standardizing data for {sport}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/data/refresh/{sport}')
def refresh_data(sport: str, series: Optional[str] = None):
    """
    Force reload data from disk for a sport.
    Useful after manual edits or downloads.
    """
    try:
        # Clear any cached data
        s, label = SportFactory.get_sport(sport, series)
        
        # Force reload
        df = s.load_data()
        
        # Get column info
        scan_report = None
        if COLUMN_STANDARDIZER:
            scan_report = COLUMN_STANDARDIZER.scan(df, sport).to_dict()
        
        return {
            "sport": sport,
            "rows": len(df),
            "columns": len(df.columns),
            "column_list": df.columns.tolist(),
            "scan_report": scan_report
        }
        
    except Exception as e:
        logger.error(f"Error refreshing data for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/data/add-alias')
def add_column_alias(sport: str, standard_name: str, new_alias: str):
    """Add a new column alias mapping."""
    if COLUMN_STANDARDIZER is None:
        raise HTTPException(status_code=500, detail="ColumnStandardizer not available")
    
    success = COLUMN_STANDARDIZER.add_alias(sport, standard_name, new_alias)
    
    if success:
        return {"success": True, "message": f"Added alias '{new_alias}' -> '{standard_name}' for {sport}"}
    else:
        return {"success": False, "message": "Alias already exists or error adding"}


@app.get('/data/quality/{sport}')
def analyze_data_quality(sport: str, series: Optional[str] = None):
    """
    Analyze data quality and sufficiency for a sport.
    Returns detailed statistics about the dataset including issues and recommendations.
    """
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        features = s.get_feature_columns()
        targets = s.get_target_columns()
        
        # Get all feature column names
        all_features = []
        for col_list in features.values():
            all_features.extend(col_list)
        
        # Basic stats
        total_rows = len(df)
        total_columns = len(df.columns)
        
        # Missing value analysis
        missing_by_col = {}
        for col in all_features:
            if col in df.columns:
                missing_pct = df[col].isna().sum() / total_rows * 100
                if missing_pct > 0:
                    missing_by_col[col] = round(missing_pct, 2)
        
        # Class balance analysis (for classification)
        class_balance = {}
        classification_target = targets.get('classification')
        if classification_target and not isinstance(classification_target, list):
            if classification_target in df.columns:
                value_counts = df[classification_target].value_counts(normalize=True).to_dict()
                class_balance = {str(k): round(v * 100, 2) for k, v in value_counts.items()}
        elif isinstance(classification_target, list):
            # Multi-target (NASCAR)
            for target in classification_target:
                if target in df.columns:
                    value_counts = df[target].value_counts(normalize=True).to_dict()
                    class_balance[target] = {str(k): round(v * 100, 2) for k, v in value_counts.items()}
        
        # Feature coverage (how many rows have non-null values for key features)
        feature_coverage = {}
        for col in all_features[:20]:  # Top 20 features
            if col in df.columns:
                coverage = (df[col].notna().sum() / total_rows) * 100
                feature_coverage[col] = round(coverage, 2)
        
        # Data range
        time_col = 'schedule_season' if 'schedule_season' in df.columns else 'year' if 'year' in df.columns else None
        date_range = {}
        if time_col and time_col in df.columns:
            date_range = {
                "column": time_col,
                "min": int(df[time_col].min()) if pd.notna(df[time_col].min()) else None,
                "max": int(df[time_col].max()) if pd.notna(df[time_col].max()) else None,
                "unique_periods": int(df[time_col].nunique())
            }
        
        # Issues and recommendations
        issues = []
        recommendations = []
        
        # Check sample size
        if total_rows < 1000:
            issues.append(f"Very small dataset ({total_rows} rows). Models may not generalize well.")
            recommendations.append("Collect more historical data if possible.")
        elif total_rows < 5000:
            issues.append(f"Moderate dataset size ({total_rows} rows). Adequate for basic models.")
        
        # Check class balance
        if class_balance and not isinstance(classification_target, list):
            minority_pct = min(class_balance.values()) if class_balance else 50
            if minority_pct < 5:
                issues.append(f"Severe class imbalance ({minority_pct}% minority class). Model may just predict majority class.")
                recommendations.append("Consider using class weights, SMOTE, or a different target with better balance.")
            elif minority_pct < 20:
                issues.append(f"Class imbalance ({minority_pct}% minority class). May affect precision/recall.")
                recommendations.append("Use balanced class weights during training.")
        
        # Check missing values
        high_missing = {k: v for k, v in missing_by_col.items() if v > 30}
        if high_missing:
            issues.append(f"{len(high_missing)} features have >30% missing values.")
            recommendations.append("Consider dropping or imputing features with high missing rates.")
        
        # Sufficiency score (0-100)
        sufficiency_score = 100
        if total_rows < 1000:
            sufficiency_score -= 40
        elif total_rows < 5000:
            sufficiency_score -= 15
        
        if high_missing:
            sufficiency_score -= 10 * min(len(high_missing), 3)
        
        if class_balance and not isinstance(classification_target, list):
            minority_pct = min(class_balance.values()) if class_balance else 50
            if minority_pct < 5:
                sufficiency_score -= 30
            elif minority_pct < 20:
                sufficiency_score -= 15
        
        sufficiency_score = max(0, sufficiency_score)
        
        # Rating
        if sufficiency_score >= 80:
            rating = "GOOD - Sufficient data for reliable predictions"
        elif sufficiency_score >= 60:
            rating = "MODERATE - Predictions may have limitations"
        elif sufficiency_score >= 40:
            rating = "LIMITED - Use predictions with caution"
        else:
            rating = "INSUFFICIENT - Need more/better data"
        
        return {
            "sport": sport,
            "series": label,
            "summary": {
                "total_rows": total_rows,
                "total_columns": total_columns,
                "features_available": len(all_features),
                "sufficiency_score": sufficiency_score,
                "rating": rating
            },
            "date_range": date_range,
            "class_balance": class_balance,
            "feature_coverage": feature_coverage,
            "missing_values": missing_by_col,
            "issues": issues,
            "recommendations": recommendations
        }
        
    except Exception as e:
        logger.error(f"Error analyzing data quality: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/data/quality/{sport}/detailed')
def analyze_data_quality_detailed(sport: str, series: Optional[str] = None):
    """
    Enhanced data quality analysis with feature correlations, 
    missing features, and ML-driven improvement recommendations.
    """
    from src.data_analyzer import DataAnalyzer
    
    try:
        # Get basic quality data first
        basic_quality = analyze_data_quality(sport, series)
        
        # Get the dataframe for additional analysis
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        features = s.get_feature_columns()
        all_features = []
        for col_list in features.values():
            all_features.extend(col_list)
        
        # Correlation analysis
        correlations = DataAnalyzer.analyze_feature_correlations(df, all_features)
        
        # Missing ideal features
        missing_features = DataAnalyzer.analyze_missing_features(sport, all_features)
        
        # ML-driven recommendations
        recommendations = DataAnalyzer.generate_recommendations(basic_quality, sport)
        
        # Feature importance from trained model
        feature_impact = DataAnalyzer.get_feature_impact_from_model(sport, series)
        
        return {
            **basic_quality,
            "correlations": correlations,
            "missing_ideal_features": missing_features[:5],
            "improvement_recommendations": recommendations,
            "feature_impact": feature_impact
        }
        
    except Exception as e:
        logger.error(f"Error in detailed data quality analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/data/quality/all')
def analyze_all_sports_quality():
    """Get data quality summary for all supported sports."""
    sports = ['nfl', 'nba', 'nascar']
    results = {}
    
    for sport in sports:
        try:
            series = 'cup' if sport == 'nascar' else None
            quality = analyze_data_quality(sport, series)
            results[sport] = {
                "summary": quality.get("summary", {}),
                "issues_count": len(quality.get("issues", [])),
                "status": "ok" if quality.get("summary", {}).get("sufficiency_score", 0) >= 60 else "warning"
            }
        except Exception as e:
            results[sport] = {
                "summary": {"error": str(e)},
                "issues_count": 0,
                "status": "error"
            }
    
    return {"sports": results, "timestamp": pd.Timestamp.now().isoformat()}


@app.get('/data/datasets/{sport}')
def get_datasets(sport: str):
    return DATASET_MANAGER.get_datasets(sport)

@app.get('/data/datasets/{sport}/{dataset_id:path}/metadata')
def get_dataset_metadata(sport: str, dataset_id: str):
    """Get metadata for a specific dataset."""
    # Return basic info since Kaggle is deprecated
    return {
        "dataset_id": dataset_id,
        "metadata": {"sport": sport},
        "update_status": None
    }


class AddDatasetRequest(BaseModel):
    dataset_id: str
    type: str = "api"  # 'api', 'github', etc.

@app.post('/data/datasets/{sport}')
def add_dataset(sport: str, req: AddDatasetRequest):
    result = DATASET_MANAGER.add_dataset(sport, req.dataset_id, req.type)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.delete('/data/datasets/{sport}/{dataset_id:path}')
def remove_dataset(sport: str, dataset_id: str):
    # dataset_id might contain slashes "owner/dataset", handled by :path in route
    success = DATASET_MANAGER.remove_dataset(sport, dataset_id)
    if not success:
         raise HTTPException(status_code=404, detail="Dataset not found")
    return {"success": True}

@app.post('/data/check-updates/{sport}')
def check_updates(sport: str):
    """Check for available data updates. Now returns basic info since Kaggle is deprecated."""
    # Return empty since we no longer use Kaggle for update checking
    # NFL uses nflverse (GitHub), NBA uses hoopR/stats.nba.com
    return {"message": f"Use Import Data to fetch latest {sport} data from official sources"}

@app.get('/data/history/{sport}')
def get_history(sport: str):
    data_dir = REPO_ROOT / 'data' / sport
    updater = BaseDataUpdater(data_dir) # Use base to just read history
    return updater.get_history()

# Unified update endpoint
@app.post('/data/update/{sport}')
def update_data(sport: str, dataset: Optional[str] = None):
    # Special handling for NASCAR (GitHub) vs others (API-based)
    # Ideally should be unified in DatasetManager too but NASCAR is special structure
    if sport == 'nascar' and not dataset:
        try:
            updater = NASCARDataUpdater(NASCAR_DATA_DIR)
            return updater.update()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
    # Generic Multi-Dataset Update
    data_dir = REPO_ROOT / 'data' / sport
    datasets = DATASET_MANAGER.get_datasets(sport)
    
    # For NFL/NBA, redirect to dedicated import endpoints
    # Legacy endpoint - just return status message
    return {
        "success": True,
        "message": f"Use /db/import/{sport} endpoint for full data import from official sources (nflverse, hoopR)"
    }


class RetrainRequest(BaseModel):
    task: str = "classification"
    series: Optional[str] = None


@app.post('/data/retrain/{sport}')
def retrain_model(sport: str, request: RetrainRequest):
    """
    Retrain a model for the specified sport.
    """
    try:
        # Get sport instance
        sport_instance, series_label = SportFactory.get_sport(sport, request.series)
        
        # Determine output directory
        out_dir = MODELS_DIR / sport
        if series_label:
            out_dir = out_dir / series_label
        
        # Run training using the correct function
        from train import train_and_evaluate_sport
        
        model_path, metrics_path, metrics = train_and_evaluate_sport(
            sport=sport_instance,
            task=request.task,
            out_dir=out_dir
        )
        
        # Clear model cache so new model is used
        with CACHE_LOCK:
            keys_to_remove = [k for k in MODEL_CACHE if k[0] == sport]
            for k in keys_to_remove:
                del MODEL_CACHE[k]
        
        return {
            "success": True,
            "sport": sport,
            "series": series_label,
            "task": request.task,
            "metrics": metrics
        }
        
    except Exception as e:
        logger.error(f"Error retraining {sport} model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Chart Data Endpoints =====

@app.get('/data/charts/{sport}/correlation')
def get_correlation_chart(sport: str, series: Optional[str] = None):
    """Get feature correlation matrix for visualization."""
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {sport}")
        
        feats = s.get_feature_columns()
        numeric_cols = feats.get('numeric', [])
        
        # Filter to existing columns
        numeric_cols = [c for c in numeric_cols if c in df.columns]
        
        if len(numeric_cols) < 2:
            return {"correlation_matrix": [], "features": []}
        
        # Limit to top 15 features for readability
        numeric_cols = numeric_cols[:15]
        
        # Calculate correlation matrix
        corr_df = df[numeric_cols].corr()
        
        # Convert to list of lists for JSON
        matrix = []
        for i, row_feat in enumerate(numeric_cols):
            row_data = []
            for j, col_feat in enumerate(numeric_cols):
                val = corr_df.loc[row_feat, col_feat]
                row_data.append(round(float(val), 3) if not pd.isna(val) else 0)
            matrix.append(row_data)
        
        return {
            "features": numeric_cols,
            "correlation_matrix": matrix
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting correlation for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/data/charts/{sport}/distribution')
def get_distribution_chart(sport: str, series: Optional[str] = None):
    """Get target class distribution for visualization."""
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {sport}")
        
        targets = s.get_target_columns()
        classification_target = targets.get('classification')
        
        if isinstance(classification_target, list):
            classification_target = classification_target[0] if classification_target else None
        
        distributions = []
        
        # Get distribution for classification target(s)
        target_cols = [classification_target] if isinstance(classification_target, str) else (classification_target or [])
        
        for target in target_cols:
            if target and target in df.columns:
                value_counts = df[target].value_counts()
                dist = {
                    "target": target,
                    "labels": [str(k) for k in value_counts.index.tolist()],
                    "values": value_counts.values.tolist(),
                    "positive_rate": float(df[target].mean()) if df[target].dtype in ['int64', 'float64', 'bool'] else None
                }
                distributions.append(dist)
        
        return {"distributions": distributions}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting distribution for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/data/charts/{sport}/coverage')
def get_coverage_chart(sport: str, series: Optional[str] = None):
    """Get feature coverage (% non-null) for visualization."""
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {sport}")
        
        feats = s.get_feature_columns()
        all_features = feats.get('categorical', []) + feats.get('boolean', []) + feats.get('numeric', [])
        
        coverage_data = []
        for feat in all_features:
            if feat in df.columns:
                non_null = df[feat].notna().sum()
                total = len(df)
                coverage = round(100 * non_null / total, 1) if total > 0 else 0
                coverage_data.append({
                    "feature": feat,
                    "coverage": coverage,
                    "non_null": int(non_null),
                    "total": int(total)
                })
        
        # Sort by coverage ascending (worst first)
        coverage_data.sort(key=lambda x: x['coverage'])
        
        return {
            "coverage": coverage_data,
            "avg_coverage": round(sum(c['coverage'] for c in coverage_data) / len(coverage_data), 1) if coverage_data else 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting coverage for {sport}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Trends Analysis Endpoints =====

# ===== NASCAR Team-Specific Endpoints (must come before generic patterns) =====

@app.get('/trends/nascar/teams')
def get_nascar_teams(series: Optional[str] = None):
    """Get list of NASCAR teams with basic stats."""
    try:
        s, label = SportFactory.get_sport('nascar', series)
        df = s.load_data()
        
        if df.empty or 'team_name' not in df.columns:
            return {"teams": [], "type": "team"}
        
        # Get unique teams with aggregated stats
        teams_data = []
        for team in df['team_name'].dropna().unique():
            team_df = df[df['team_name'] == team]
            if len(team_df) < 5:  # Skip teams with very few races
                continue
            
            # Calculate basic stats
            wins = len(team_df[team_df.get('finish', team_df.get('finishing_position', pd.Series())) == 1]) if 'finish' in team_df.columns or 'finishing_position' in team_df.columns else 0
            finish_col = 'finish' if 'finish' in team_df.columns else 'finishing_position'
            avg_finish = team_df[finish_col].mean() if finish_col in team_df.columns else 0
            
            # Get drivers for this team
            drivers = team_df['driver'].dropna().unique().tolist() if 'driver' in team_df.columns else []
            
            teams_data.append({
                "name": team,
                "races": len(team_df),
                "wins": wins,
                "avg_finish": round(avg_finish, 1) if avg_finish else 0,
                "driver_count": len(drivers),
                "drivers": drivers[:5]  # Top 5 drivers
            })
        
        # Sort by wins descending
        teams_data.sort(key=lambda x: x['wins'], reverse=True)
        
        return {"teams": teams_data, "type": "team"}
        
    except Exception as e:
        logger.error(f"Error getting NASCAR teams: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/trends/nascar/team/{team_name}')
def get_nascar_team_trends(
    team_name: str,
    start_year: int = 2015,
    end_year: int = 2030,
    series: Optional[str] = None
):
    """Get comprehensive trend analysis for a NASCAR team."""
    try:
        s, label = SportFactory.get_sport('nascar', series)
        df = s.load_data()
        
        if df.empty:
            raise HTTPException(status_code=404, detail="No NASCAR data available")
        
        # Filter by team (case-insensitive)
        team_lower = team_name.lower()
        if 'team_name' in df.columns:
            team_df = df[df['team_name'].str.lower().str.contains(team_lower, na=False)].copy()
        else:
            raise HTTPException(status_code=400, detail="Team data not available")
        
        if team_df.empty:
            return {"entity": team_name, "sport": "nascar", "entity_type": "team", "overall": {}, "by_season": [], "splits": {}, "drivers": []}
        
        # Year column detection
        year_col = 'schedule_season' if 'schedule_season' in team_df.columns else ('year' if 'year' in team_df.columns else None)
        
        # Filter by year range
        if year_col:
            team_df = team_df[(team_df[year_col] >= start_year) & (team_df[year_col] <= end_year)]
        
        # Finish column
        finish_col = 'finish' if 'finish' in team_df.columns else 'finishing_position'
        
        # ===== Overall Stats =====
        total_races = len(team_df)
        wins = len(team_df[team_df[finish_col] == 1]) if finish_col in team_df.columns else 0
        top5 = len(team_df[team_df[finish_col] <= 5]) if finish_col in team_df.columns else 0
        top10 = len(team_df[team_df[finish_col] <= 10]) if finish_col in team_df.columns else 0
        avg_finish = team_df[finish_col].mean() if finish_col in team_df.columns else 0
        
        overall = {
            "races": total_races,
            "wins": wins,
            "top5": top5,
            "top10": top10,
            "win_pct": round(wins / total_races * 100, 1) if total_races > 0 else 0,
            "top5_pct": round(top5 / total_races * 100, 1) if total_races > 0 else 0,
            "avg_finish": round(avg_finish, 1) if avg_finish else 0
        }
        
        # ===== By Season Breakdown =====
        by_season = []
        if year_col:
            for year in sorted(team_df[year_col].unique()):
                year_df = team_df[team_df[year_col] == year]
                year_wins = len(year_df[year_df[finish_col] == 1]) if finish_col in year_df.columns else 0
                year_top5 = len(year_df[year_df[finish_col] <= 5]) if finish_col in year_df.columns else 0
                by_season.append({
                    "year": int(year),
                    "races": len(year_df),
                    "wins": year_wins,
                    "top5": year_top5,
                    "avg_finish": round(year_df[finish_col].mean(), 1) if finish_col in year_df.columns else 0
                })
        
        # ===== Track Type Splits =====
        splits = {}
        if 'track_type' in team_df.columns:
            for track_type in team_df['track_type'].dropna().unique():
                track_df = team_df[team_df['track_type'] == track_type]
                track_wins = len(track_df[track_df[finish_col] == 1]) if finish_col in track_df.columns else 0
                splits[track_type] = {
                    "races": len(track_df),
                    "wins": track_wins,
                    "avg_finish": round(track_df[finish_col].mean(), 1) if finish_col in track_df.columns else 0
                }
        
        # ===== Drivers List =====
        drivers = []
        if 'driver' in team_df.columns:
            for driver in team_df['driver'].dropna().unique():
                driver_df = team_df[team_df['driver'] == driver]
                driver_wins = len(driver_df[driver_df[finish_col] == 1]) if finish_col in driver_df.columns else 0
                drivers.append({
                    "name": driver,
                    "races": len(driver_df),
                    "wins": driver_wins,
                    "avg_finish": round(driver_df[finish_col].mean(), 1) if finish_col in driver_df.columns else 0
                })
            # Sort by races descending
            drivers.sort(key=lambda x: x['races'], reverse=True)
        
        return {
            "entity": team_name,
            "sport": "nascar",
            "entity_type": "team",
            "overall": overall,
            "by_season": by_season,
            "splits": splits,
            "drivers": drivers[:20],  # Top 20 drivers
            "trends": {
                "seasons_analyzed": len(by_season),
                "data_range": f"{by_season[0]['year']}-{by_season[-1]['year']}" if by_season else ""
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting team trends for {team_name}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/trends/{sport}/entities')
def get_available_entities(sport: str, series: Optional[str] = None):
    """Get list of available teams/drivers for trends analysis."""
    try:
        logger.info(f"GET /trends/{sport}/entities - series={series}")
        s, label = SportFactory.get_sport(sport, series)
        
        # Force data load to populate internal caches
        df = s.load_data()
        logger.info(f"Loaded {len(df)} rows for {sport}, columns: {list(df.columns)[:10]}...")
        
        is_nascar = 'nascar' in sport.lower()
        logger.info(f"is_nascar={is_nascar}")
        
        if is_nascar:
            # NASCAR: Get drivers using the sport's native method
            try:
                entities = s.get_entities()  # Returns driver names
                logger.info(f"NASCAR get_entities returned {len(entities) if entities else 0} entries")
                if entities:
                    result = sorted(entities)[:200]
                    logger.info(f"Returning {len(result)} NASCAR drivers: {result[:5]}...")
                    return {"entities": result, "type": "driver"}
            except Exception as e:
                logger.warning(f"get_entities failed for NASCAR: {e}")
            
            # Fallback: try get_drivers
            try:
                entities = s.get_drivers()
                logger.info(f"NASCAR get_drivers returned {len(entities) if entities else 0} entries")
                if entities:
                    result = sorted(entities)[:200]
                    return {"entities": result, "type": "driver"}
            except:
                pass
                
        else:
            # NFL/NBA: Get teams using the sport's native method  
            try:
                teams = s.get_teams()
                logger.info(f"{sport} get_teams returned {len(teams) if teams else 0} teams: {teams[:5] if teams else []}...")
                if teams:
                    result = sorted(teams)[:200]
                    logger.info(f"Returning {len(result)} teams for {sport}")
                    return {"entities": result, "type": "team"}
            except Exception as e:
                logger.warning(f"get_teams failed for {sport}: {e}")
            
            # Fallback: try get_entities
            try:
                entities = s.get_entities()
                logger.info(f"{sport} get_entities returned {len(entities) if entities else 0} entries")
                if entities:
                    result = sorted(entities)[:200]
                    return {"entities": result, "type": "team"}
            except:
                pass
            
            # Fallback 2: Extract directly from dataframe columns (home_team, away_team)
            logger.info(f"Trying direct column extraction for {sport}...")
            teams = set()
            for col in ['home_team', 'away_team', 'team_home', 'team_away']:
                if col in df.columns:
                    team_vals = df[col].dropna().unique().tolist()
                    for t in team_vals:
                        if isinstance(t, str) and len(t) > 2:
                            teams.add(t)
            
            if teams:
                result = sorted(list(teams))[:200]
                logger.info(f"Extracted {len(result)} teams from dataframe columns for {sport}")
                return {"entities": result, "type": "team"}
        
        logger.warning(f"No entities found for {sport}")
        return {"entities": [], "type": "unknown"}
        
    except Exception as e:
        logger.error(f"Error getting entities for {sport}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/trends/{sport}/{entity}')
def get_entity_trends(
    sport: str, 
    entity: str,
    start_year: int = 2015,
    end_year: int = 2030,
    entity_type: str = "team",
    series: Optional[str] = None
):
    """Get comprehensive trend analysis for a team/driver."""
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {sport}")
        
        # Determine entity type based on sport
        is_nascar = 'nascar' in sport.lower()
        
        # Year column detection
        year_col = None
        for col in ['year', 'season', 'schedule_season']:
            if col in df.columns:
                year_col = col
                break
        
        # Filter by year range
        if year_col:
            df = df[(df[year_col] >= start_year) & (df[year_col] <= end_year)]
        
        # Find matching entity based on sport type
        entity_lower = entity.lower()
        entity_df = pd.DataFrame()
        
        if is_nascar:
            # NASCAR: Match by driver name
            if 'driver' in df.columns:
                entity_df = df[df['driver'].str.lower().str.contains(entity_lower, na=False)].copy()
        else:
            # NFL/NBA: Try multiple team column patterns
            team_cols_to_check = [
                ('home_team', 'away_team'),
                ('team_home', 'team_away'),
            ]
            
            for home_col, away_col in team_cols_to_check:
                if home_col in df.columns and away_col in df.columns:
                    home_mask = df[home_col].astype(str).str.lower().str.contains(entity_lower, na=False)
                    away_mask = df[away_col].astype(str).str.lower().str.contains(entity_lower, na=False)
                    entity_df = df[home_mask | away_mask].copy()
                    break
            
            # Fallback: check team_favorite_id for NFL
            if entity_df.empty and 'team_favorite_id' in df.columns:
                entity_df = df[df['team_favorite_id'].astype(str).str.lower().str.contains(entity_lower, na=False)].copy()
        
        if entity_df.empty:
            return {
                "entity": entity,
                "sport": sport,
                "error": "No data found for entity",
                "overall": {"games": 0, "wins": 0, "losses": 0, "pct": 0},
                "by_season": [],
                "recent_form": [],
                "splits": {},
                "trends": {}
            }
        
        # ===== Calculate Overall Stats =====
        total_games = len(entity_df)
        
        # Determine win column
        if is_nascar:
            # NASCAR: Count top positions - try different column names
            finish_col = None
            for col in ['finish', 'finishing_position', 'Finish', 'FinishingPosition']:
                if col in entity_df.columns:
                    finish_col = col
                    break
            
            if finish_col:
                # Convert to numeric to handle any string values
                entity_df[finish_col] = pd.to_numeric(entity_df[finish_col], errors='coerce')
                wins = len(entity_df[entity_df[finish_col] == 1])
                top5 = len(entity_df[entity_df[finish_col] <= 5])
                top10 = len(entity_df[entity_df[finish_col] <= 10])
                avg_finish = entity_df[finish_col].mean()
            else:
                wins, top5, top10, avg_finish = 0, 0, 0, 0
                logger.warning(f"No finish column found for NASCAR driver {entity}. Columns: {list(entity_df.columns)[:10]}")
            
            overall = {
                "races": total_games,
                "wins": wins,
                "top5": top5,
                "top10": top10,
                "win_pct": round(wins / total_games * 100, 1) if total_games > 0 else 0,
                "top5_pct": round(top5 / total_games * 100, 1) if total_games > 0 else 0,
                "top10_pct": round(top10 / total_games * 100, 1) if total_games > 0 else 0,
                "avg_finish": round(avg_finish, 1) if pd.notna(avg_finish) and avg_finish else 0
            }
        else:
            # NFL/NBA: Count wins
            # Detect home/away column names dynamically
            home_col = away_col = None
            for hc, ac in [('home_team', 'away_team'), ('team_home', 'team_away')]:
                if hc in entity_df.columns and ac in entity_df.columns:
                    home_col, away_col = hc, ac
                    break
            
            if home_col and away_col:
                # Calculate wins when entity is home vs away
                home_games = entity_df[entity_df[home_col].astype(str).str.lower().str.contains(entity_lower, na=False)]
                away_games = entity_df[entity_df[away_col].astype(str).str.lower().str.contains(entity_lower, na=False)]
                
                home_wins = 0
                away_wins = 0
                
                # Check for different score column patterns
                home_score_col = away_score_col = None
                for hsc, asc in [('score_home', 'score_away'), ('home_score', 'away_score')]:
                    if hsc in entity_df.columns and asc in entity_df.columns:
                        home_score_col, away_score_col = hsc, asc
                        break
                
                if home_score_col and away_score_col:
                    home_wins = len(home_games[home_games[home_score_col] > home_games[away_score_col]])
                    away_wins = len(away_games[away_games[away_score_col] > away_games[home_score_col]])
                elif 'home_win' in entity_df.columns:
                    home_wins = len(home_games[home_games['home_win'] == 1])
                    away_wins = len(away_games[away_games['home_win'] == 0])
                elif 'home_team_win' in entity_df.columns:
                    home_wins = len(home_games[home_games['home_team_win'] == 1])
                    away_wins = len(away_games[away_games['home_team_win'] == 0])
                
                total_wins = home_wins + away_wins
                total_losses = total_games - total_wins
                
                # Points if available
                ppg = 0
                if home_score_col:
                    home_pts = home_games[home_score_col].mean() if len(home_games) > 0 else 0
                    away_pts = away_games[away_score_col].mean() if len(away_games) > 0 else 0
                    ppg = (home_pts * len(home_games) + away_pts * len(away_games)) / total_games if total_games > 0 else 0
                
                overall = {
                    "games": total_games,
                    "wins": total_wins,
                    "losses": total_losses,
                    "pct": round(total_wins / total_games * 100, 1) if total_games > 0 else 0,
                    "ppg": round(ppg, 1) if ppg else 0,
                    "home_record": f"{home_wins}-{len(home_games) - home_wins}",
                    "away_record": f"{away_wins}-{len(away_games) - away_wins}"
                }
            else:
                overall = {"games": total_games, "wins": 0, "losses": 0, "pct": 0}
        
        # ===== By Season Breakdown =====
        by_season = []
        if year_col:
            for year in sorted(entity_df[year_col].unique()):
                year_df = entity_df[entity_df[year_col] == year].copy()
                if is_nascar:
                    # Use finish_col detected earlier
                    if finish_col and finish_col in year_df.columns:
                        year_df[finish_col] = pd.to_numeric(year_df[finish_col], errors='coerce')
                        year_wins = len(year_df[year_df[finish_col] == 1])
                        year_top5 = len(year_df[year_df[finish_col] <= 5])
                        year_avg = year_df[finish_col].mean()
                    else:
                        year_wins, year_top5, year_avg = 0, 0, 0
                    
                    by_season.append({
                        "year": int(year),
                        "races": len(year_df),
                        "wins": year_wins,
                        "top5": year_top5,
                        "avg_finish": round(year_avg, 1) if pd.notna(year_avg) else 0
                    })
                else:
                    # Team sports - calculate wins for this year using flexible column detection
                    year_wins = 0
                    
                    # Find home/away columns
                    home_col = away_col = None
                    for hc, ac in [('home_team', 'away_team'), ('team_home', 'team_away')]:
                        if hc in year_df.columns and ac in year_df.columns:
                            home_col, away_col = hc, ac
                            break
                    
                    if home_col and away_col:
                        home_g = year_df[year_df[home_col].astype(str).str.lower().str.contains(entity_lower, na=False)]
                        away_g = year_df[year_df[away_col].astype(str).str.lower().str.contains(entity_lower, na=False)]
                        
                        # Check for different score/win column patterns
                        if 'score_home' in year_df.columns and 'score_away' in year_df.columns:
                            year_wins = len(home_g[home_g['score_home'] > home_g['score_away']]) + \
                                       len(away_g[away_g['score_away'] > away_g['score_home']])
                        elif 'home_score' in year_df.columns and 'away_score' in year_df.columns:
                            year_wins = len(home_g[home_g['home_score'] > home_g['away_score']]) + \
                                       len(away_g[away_g['away_score'] > away_g['home_score']])
                        elif 'home_team_win' in year_df.columns:
                            year_wins = len(home_g[home_g['home_team_win'] == 1]) + len(away_g[away_g['home_team_win'] == 0])
                        elif 'home_win' in year_df.columns:
                            year_wins = len(home_g[home_g['home_win'] == 1]) + len(away_g[away_g['home_win'] == 0])
                    
                    by_season.append({
                        "year": int(year),
                        "games": len(year_df),
                        "wins": year_wins,
                        "losses": len(year_df) - year_wins,
                        "pct": round(year_wins / len(year_df) * 100, 1) if len(year_df) > 0 else 0
                    })
        
        # ===== Recent Form (Last 10) =====
        recent_form = []
        # Sort by date if available
        date_col = None
        for col in ['date', 'game_date', 'race_date', 'commence_time']:
            if col in entity_df.columns:
                date_col = col
                break
        
        if date_col:
            recent_df = entity_df.sort_values(date_col, ascending=False).head(10)
        else:
            recent_df = entity_df.tail(10)
        
        for _, row in recent_df.iterrows():
            if is_nascar:
                # Use finish_col detected earlier
                finish_val = row.get(finish_col) if finish_col else None
                result = f"P{int(finish_val)}" if pd.notna(finish_val) else "?"
                recent_form.append({
                    "result": result,
                    "is_win": finish_val == 1 if pd.notna(finish_val) else False,
                    "is_top5": finish_val <= 5 if pd.notna(finish_val) else False,
                    "track": str(row.get('track', ''))[:15] if 'track' in row else ''
                })
            else:
                # Determine W/L for team sports
                is_home = row.get('home_team', '').lower().__contains__(entity_lower) if 'home_team' in row else False
                if 'score_home' in row and 'score_away' in row:
                    home_won = row['score_home'] > row['score_away']
                    won = home_won if is_home else not home_won
                elif 'home_win' in row:
                    won = (row['home_win'] == 1) if is_home else (row['home_win'] == 0)
                else:
                    won = False
                
                recent_form.append({
                    "result": "W" if won else "L",
                    "is_win": won,
                    "opponent": row.get('away_team' if is_home else 'home_team', '')[:15],
                    "home": is_home
                })
        
        # ===== Splits =====
        splits = {}
        if not is_nascar and 'home_team' in entity_df.columns:
            # Home/Away split
            home_g = entity_df[entity_df['home_team'].str.lower().str.contains(entity_lower, na=False)]
            away_g = entity_df[entity_df['away_team'].str.lower().str.contains(entity_lower, na=False)]
            
            home_wins = 0
            away_wins = 0
            if 'score_home' in entity_df.columns:
                home_wins = len(home_g[home_g['score_home'] > home_g['score_away']])
                away_wins = len(away_g[away_g['score_away'] > away_g['score_home']])
            elif 'home_win' in entity_df.columns:
                home_wins = len(home_g[home_g['home_win'] == 1])
                away_wins = len(away_g[away_g['home_win'] == 0])
            
            splits["home"] = {"wins": home_wins, "losses": len(home_g) - home_wins, "games": len(home_g)}
            splits["away"] = {"wins": away_wins, "losses": len(away_g) - away_wins, "games": len(away_g)}
        
        if is_nascar and 'track_type' in entity_df.columns:
            # Track type split for NASCAR - use finish_col detected earlier
            for track_type in entity_df['track_type'].dropna().unique():
                track_df = entity_df[entity_df['track_type'] == track_type].copy()
                if finish_col and finish_col in track_df.columns:
                    track_df[finish_col] = pd.to_numeric(track_df[finish_col], errors='coerce')
                    track_wins = len(track_df[track_df[finish_col] == 1])
                    track_avg = track_df[finish_col].mean()
                else:
                    track_wins, track_avg = 0, 0
                    
                splits[str(track_type)] = {
                    "races": len(track_df),
                    "wins": track_wins,
                    "avg_finish": round(track_avg, 1) if pd.notna(track_avg) else 0
                }
        
        # ===== Trends Summary =====
        trends = {
            "last_10": sum(1 for f in recent_form[:10] if f.get('is_win', False)),
            "last_5": sum(1 for f in recent_form[:5] if f.get('is_win', False)),
            "seasons_analyzed": len(by_season),
            "data_range": f"{start_year}-{end_year}"
        }
        
        return {
            "entity": entity,
            "sport": sport,
            "entity_type": "driver" if is_nascar else "team",
            "overall": overall,
            "by_season": by_season,
            "recent_form": recent_form,
            "splits": splits,
            "trends": trends
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trends for {entity} in {sport}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ===== Power Rankings Endpoints =====

@app.get('/rankings/{sport}')
def get_power_rankings(
    sport: str,
    week: Optional[int] = None,
    season: Optional[int] = None,
    series: Optional[str] = None
):
    """Calculate and return power rankings for teams/drivers."""
    try:
        import pandas as pd
        from datetime import datetime
        
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {sport}")
        
        is_nascar = 'nascar' in sport.lower()
        current_year = datetime.now().year
        target_season = season or current_year
        
        # Year column detection
        year_col = None
        for col in ['schedule_season', 'year', 'season', 'Season']:
            if col in df.columns:
                year_col = col
                break
        
        # Filter to current/target season
        if year_col:
            df = df[df[year_col] == target_season].copy()
        
        rankings = []
        
        if is_nascar:
            # NASCAR: Rank by team performance
            team_col = None
            for col in ['team_name', 'Team', 'team']:
                if col in df.columns:
                    team_col = col
                    break
            
            if not team_col:
                return {"rankings": [], "sport": sport, "message": "No team data"}
            
            finish_col = 'finish' if 'finish' in df.columns else 'finishing_position'
            
            for team in df[team_col].dropna().unique():
                team_df = df[df[team_col] == team]
                if len(team_df) < 3:
                    continue
                
                races = len(team_df)
                if finish_col in team_df.columns:
                    team_df[finish_col] = pd.to_numeric(team_df[finish_col], errors='coerce')
                    wins = len(team_df[team_df[finish_col] == 1])
                    top5 = len(team_df[team_df[finish_col] <= 5])
                    top10 = len(team_df[team_df[finish_col] <= 10])
                    avg_finish = team_df[finish_col].mean()
                else:
                    wins, top5, top10, avg_finish = 0, 0, 0, 20
                
                # Power score: Lower avg finish is better
                win_pct = (wins / races * 100) if races > 0 else 0
                top5_pct = (top5 / races * 100) if races > 0 else 0
                
                # Score = (100 - avg_finish*2) + win_pct + top5_pct/2
                power_score = max(0, (100 - avg_finish * 2)) + win_pct + (top5_pct / 2)
                
                rankings.append({
                    "team": team,
                    "power_score": round(power_score, 1),
                    "record": f"{wins}W / {races}R",
                    "metrics": {
                        "races": races,
                        "wins": wins,
                        "top5": top5,
                        "top10": top10,
                        "avg_finish": round(avg_finish, 1) if pd.notna(avg_finish) else 0,
                        "win_pct": round(win_pct, 1),
                        "top5_pct": round(top5_pct, 1)
                    }
                })
        else:
            # NFL/NBA: Rank by team performance
            # Find team columns
            home_col = away_col = None
            for hc, ac in [('home_team', 'away_team'), ('team_home', 'team_away')]:
                if hc in df.columns and ac in df.columns:
                    home_col, away_col = hc, ac
                    break
            
            if not home_col:
                return {"rankings": [], "sport": sport, "message": "No team columns found"}
            
            # Get all unique teams
            all_teams = set(df[home_col].dropna().unique()) | set(df[away_col].dropna().unique())
            
            for team in all_teams:
                if not isinstance(team, str) or len(team) < 3:
                    continue
                
                team_lower = team.lower()
                home_games = df[df[home_col].astype(str).str.lower() == team_lower]
                away_games = df[df[away_col].astype(str).str.lower() == team_lower]
                
                total_games = len(home_games) + len(away_games)
                if total_games < 3:
                    continue
                
                # Calculate wins
                home_wins = away_wins = 0
                home_pts = away_pts = 0
                opp_pts = 0
                
                # Check for different win/score columns
                if 'home_team_win' in df.columns:
                    home_wins = len(home_games[home_games['home_team_win'] == 1])
                    away_wins = len(away_games[away_games['home_team_win'] == 0])
                elif 'home_win' in df.columns:
                    home_wins = len(home_games[home_games['home_win'] == 1])
                    away_wins = len(away_games[away_games['home_win'] == 0])
                elif 'score_home' in df.columns and 'score_away' in df.columns:
                    home_wins = len(home_games[home_games['score_home'] > home_games['score_away']])
                    away_wins = len(away_games[away_games['score_away'] > away_games['score_home']])
                
                total_wins = home_wins + away_wins
                total_losses = total_games - total_wins
                
                # Point differential
                point_diff = 0
                for hsc, asc in [('score_home', 'score_away'), ('home_score', 'away_score')]:
                    if hsc in df.columns and asc in df.columns:
                        home_pts = home_games[hsc].sum() if len(home_games) > 0 else 0
                        home_opp = home_games[asc].sum() if len(home_games) > 0 else 0
                        away_pts = away_games[asc].sum() if len(away_games) > 0 else 0
                        away_opp = away_games[hsc].sum() if len(away_games) > 0 else 0
                        point_diff = ((home_pts + away_pts) - (home_opp + away_opp)) / total_games if total_games > 0 else 0
                        break
                
                win_pct = (total_wins / total_games * 100) if total_games > 0 else 0
                
                # Power score = Win% * 0.5 + PointDiff * 2 + 50 (base)
                power_score = (win_pct * 0.5) + (point_diff * 2) + 50
                power_score = max(0, min(100, power_score))  # Clamp 0-100
                
                rankings.append({
                    "team": team,
                    "power_score": round(power_score, 1),
                    "record": f"{total_wins}-{total_losses}",
                    "metrics": {
                        "games": total_games,
                        "wins": total_wins,
                        "losses": total_losses,
                        "win_pct": round(win_pct, 1),
                        "point_diff": round(point_diff, 1),
                        "home_record": f"{home_wins}-{len(home_games) - home_wins}",
                        "away_record": f"{away_wins}-{len(away_games) - away_wins}"
                    }
                })
        
        # Sort by power score descending
        rankings.sort(key=lambda x: x['power_score'], reverse=True)
        
        # Add rank and tier
        for i, team in enumerate(rankings):
            team['rank'] = i + 1
            team['previous_rank'] = i + 1  # TODO: Load from previous week
            team['change'] = 0
            
            # Tier assignment
            total = len(rankings)
            if i < total * 0.15:
                team['tier'] = "Elite"
            elif i < total * 0.40:
                team['tier'] = "Contender"
            elif i < total * 0.70:
                team['tier'] = "Middle"
            else:
                team['tier'] = "Rebuilding"
        
        return {
            "sport": sport,
            "season": target_season,
            "generated_at": datetime.now().isoformat(),
            "total_teams": len(rankings),
            "rankings": rankings
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating rankings for {sport}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ===== Player Profile Endpoints (NBA/NFL) =====

@app.get('/players/{sport}/list')
def get_player_list(sport: str, series: Optional[str] = None):
    """Get list of available players for a sport."""
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            return {"players": [], "sport": sport}
        
        players = []
        
        # Try to find player column
        player_cols = ['player', 'player_name', 'name', 'driver']
        for col in player_cols:
            if col in df.columns:
                players = df[col].dropna().unique().tolist()
                # Clean and sort
                players = sorted([str(p) for p in players if isinstance(p, str) and len(p) > 2])
                break
        
        # If no player column, try team rosters (for team sports we may have player data elsewhere)
        if not players and 'home_player' in df.columns:
            players = list(set(df['home_player'].dropna().tolist() + df.get('away_player', pd.Series()).dropna().tolist()))
        
        return {"players": players[:500], "sport": sport, "total": len(players)}
        
    except Exception as e:
        logger.error(f"Error getting player list for {sport}: {e}")
        return {"players": [], "sport": sport, "error": str(e)}


@app.get('/players/{sport}/{player_name}/stats')
def get_player_stats(
    sport: str, 
    player_name: str,
    season: int = 2024,
    series: Optional[str] = None
):
    """Get stats for a specific player."""
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data for {sport}")
        
        # Year column detection
        year_col = None
        for col in ['year', 'season', 'schedule_season']:
            if col in df.columns:
                year_col = col
                break
        
        # Filter to season
        if year_col:
            df = df[df[year_col] == season].copy()
        
        # Find player data
        player_lower = player_name.lower()
        player_df = pd.DataFrame()
        
        player_cols = ['player', 'player_name', 'name', 'driver']
        for col in player_cols:
            if col in df.columns:
                player_df = df[df[col].astype(str).str.lower().str.contains(player_lower, na=False)]
                break
        
        if player_df.empty:
            return {
                "player": player_name,
                "team": "Unknown",
                "position": "Unknown",
                "season_stats": {},
                "last_5_games": [],
                "error": "Player not found"
            }
        
        # Get team and position if available
        team = player_df['team'].iloc[0] if 'team' in player_df.columns else "Unknown"
        position = player_df['position'].iloc[0] if 'position' in player_df.columns else "Unknown"
        
        # Calculate season stats based on sport
        season_stats = {}
        
        if 'nba' in sport.lower():
            # NBA stats
            numeric_cols = ['pts', 'points', 'reb', 'rebounds', 'ast', 'assists', 'stl', 'steals', 'blk', 'blocks', 'min', 'minutes']
            for col in numeric_cols:
                if col in player_df.columns:
                    val = player_df[col].mean()
                    if pd.notna(val):
                        key = col.upper()[:3] if len(col) > 3 else col.upper()
                        season_stats[key] = round(val, 1)
            
            season_stats['GP'] = len(player_df)
            
        elif 'nfl' in sport.lower():
            # NFL stats
            stat_cols = {
                'pass_yds': 'Pass Yds',
                'passing_yards': 'Pass Yds',
                'rush_yds': 'Rush Yds',
                'rushing_yards': 'Rush Yds',
                'rec_yds': 'Rec Yds',
                'receiving_yards': 'Rec Yds',
                'tds': 'TDs',
                'touchdowns': 'TDs',
                'pass_td': 'Pass TDs',
                'rush_td': 'Rush TDs',
                'rec_td': 'Rec TDs'
            }
            
            for col, name in stat_cols.items():
                if col in player_df.columns:
                    val = player_df[col].sum()
                    if pd.notna(val) and val > 0:
                        season_stats[name] = int(val)
            
            season_stats['Games'] = len(player_df)
        
        # Last 5 games
        last_5_games = []
        date_col = None
        for col in ['date', 'game_date', 'commence_time']:
            if col in player_df.columns:
                date_col = col
                break
        
        if date_col:
            recent = player_df.sort_values(date_col, ascending=False).head(5)
        else:
            recent = player_df.tail(5)
        
        for _, row in recent.iterrows():
            game = {
                "date": str(row.get(date_col, ''))[:10] if date_col else '',
                "opponent": row.get('opponent', row.get('opp', '')),
                "stats": []
            }
            
            # Add relevant stats to game log
            if 'nba' in sport.lower():
                for col in ['pts', 'reb', 'ast', 'stl', 'blk']:
                    if col in row:
                        game["stats"].append(str(int(row[col])) if pd.notna(row[col]) else '0')
            else:
                for col in ['pass_yds', 'rush_yds', 'rec_yds', 'tds']:
                    if col in row:
                        game["stats"].append(str(int(row[col])) if pd.notna(row[col]) else '0')
            
            last_5_games.append(game)
        
        return {
            "player": player_name,
            "team": str(team),
            "position": str(position),
            "season_stats": season_stats,
            "last_5_games": last_5_games
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting player stats for {player_name}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/players/{sport}/compare')
def compare_players(
    sport: str,
    p1: str,
    p2: str,
    season: int = 2024,
    series: Optional[str] = None
):
    """Compare two players side-by-side."""
    try:
        # Get stats for both players
        player1_stats = get_player_stats(sport, p1, season, series)
        player2_stats = get_player_stats(sport, p2, season, series)
        
        return {
            "player1": player1_stats,
            "player2": player2_stats,
            "season": season
        }
        
    except Exception as e:
        logger.error(f"Error comparing players: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== Edge Predictions Endpoints =====

@app.get('/edge/{sport}/players')
def get_player_edge_scores(
    sport: str,
    season: int = 2024,
    limit: int = 50,
    series: Optional[str] = None
):
    """Calculate edge scores for players based on recent form vs season average.
    
    Edge Score = (Recent Avg - Season Avg) / Season StdDev
    Positive = Hot (over-performing), Negative = Cold (under-performing)
    """
    try:
        s, label = SportFactory.get_sport(sport, series)
        df = s.load_data()
        
        if df.empty:
            return {"players": [], "sport": sport, "message": "No data available"}
        
        # Year column detection
        year_col = None
        for col in ['year', 'season', 'schedule_season']:
            if col in df.columns:
                year_col = col
                break
        
        # Filter to season
        if year_col:
            df = df[df[year_col] == season].copy()
        
        if df.empty:
            return {"players": [], "sport": sport, "message": f"No data for {season} season"}
        
        # Find player column
        player_col = None
        for col in ['player', 'player_name', 'name', 'driver']:
            if col in df.columns:
                player_col = col
                break
        
        if not player_col:
            return {"players": [], "sport": sport, "message": "No player column found"}
        
        players_data = []
        
        # Determine primary stat column based on sport
        if 'nba' in sport.lower():
            primary_stat = 'pts' if 'pts' in df.columns else 'points'
            secondary_stats = ['reb', 'ast', 'stl', 'blk']
            stat_labels = {'pts': 'PTS', 'reb': 'REB', 'ast': 'AST'}
        elif 'nfl' in sport.lower():
            primary_stat = 'pass_yds' if 'pass_yds' in df.columns else 'passing_yards'
            secondary_stats = ['rush_yds', 'rec_yds', 'tds']
            stat_labels = {'pass_yds': 'Pass Yds', 'rush_yds': 'Rush Yds', 'rec_yds': 'Rec Yds'}
        else:
            primary_stat = 'finish' if 'finish' in df.columns else 'finishing_position'
            secondary_stats = []
            stat_labels = {'finish': 'Finish'}
        
        if primary_stat not in df.columns:
            return {"players": [], "sport": sport, "message": f"Primary stat column '{primary_stat}' not found"}
        
        # Get unique players
        unique_players = df[player_col].dropna().unique()
        
        for player_name in unique_players:
            if not isinstance(player_name, str) or len(player_name) < 3:
                continue
            
            player_df = df[df[player_col] == player_name].copy()
            
            if len(player_df) < 5:  # Need at least 5 games for meaningful analysis
                continue
            
            # Convert stat to numeric
            player_df[primary_stat] = pd.to_numeric(player_df[primary_stat], errors='coerce')
            player_df = player_df.dropna(subset=[primary_stat])
            
            if len(player_df) < 5:
                continue
            
            # Calculate season stats
            season_avg = player_df[primary_stat].mean()
            season_std = player_df[primary_stat].std()
            
            if season_std == 0 or pd.isna(season_std):
                season_std = 1  # Avoid division by zero
            
            # Calculate recent form (last 5 games)
            date_col = None
            for col in ['date', 'game_date', 'commence_time']:
                if col in player_df.columns:
                    date_col = col
                    break
            
            if date_col:
                player_df = player_df.sort_values(date_col, ascending=False)
            
            recent_5 = player_df.head(5)[primary_stat]
            recent_avg = recent_5.mean()
            
            # Calculate edge score
            edge_score = (recent_avg - season_avg) / season_std
            
            # Determine trend
            if edge_score > 1:
                trend = "🔥 Hot"
                trend_color = "success"
            elif edge_score > 0.5:
                trend = "📈 Warming"
                trend_color = "info"
            elif edge_score < -1:
                trend = "❄️ Cold"
                trend_color = "error"
            elif edge_score < -0.5:
                trend = "📉 Cooling"
                trend_color = "warning"
            else:
                trend = "➡️ Steady"
                trend_color = "default"
            
            # Get team if available
            team = player_df['team'].iloc[0] if 'team' in player_df.columns else "Unknown"
            position = player_df['position'].iloc[0] if 'position' in player_df.columns else "Unknown"
            
            players_data.append({
                "player": str(player_name),
                "team": str(team),
                "position": str(position),
                "edge_score": round(edge_score, 2),
                "trend": trend,
                "trend_color": trend_color,
                "season_avg": round(season_avg, 1),
                "recent_avg": round(recent_avg, 1),
                "games_played": len(player_df),
                "primary_stat": stat_labels.get(primary_stat, primary_stat),
                "last_5": [round(x, 1) for x in recent_5.tolist()]
            })
        
        # Sort by absolute edge score (most extreme performers first)
        players_data.sort(key=lambda x: abs(x['edge_score']), reverse=True)
        
        # Apply limit
        players_data = players_data[:limit]
        
        # Also provide hot/cold splits
        hot_players = [p for p in players_data if p['edge_score'] > 0.5][:10]
        cold_players = [p for p in players_data if p['edge_score'] < -0.5][:10]
        
        return {
            "sport": sport,
            "season": season,
            "total_analyzed": len(players_data),
            "primary_stat": stat_labels.get(primary_stat, primary_stat),
            "players": players_data,
            "hot_players": hot_players,
            "cold_players": cold_players
        }
        
    except Exception as e:
        logger.error(f"Error calculating edge scores for {sport}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ========== College Baseball Endpoints ==========

class CollegeBaseballImportRequest(BaseModel):
    division: int = 1  # 1, 2, or 3
    year: Optional[int] = None  # Defaults to current year
    team_id: Optional[int] = None  # Optional: import specific team only


async def run_baseball_import_with_logging(division, year, team_id, source):
    """Background task for baseball import with progress tracking and DB logging."""
    from scripts.college_baseball_importer import run_college_baseball_import
    from src.config import DATABASE_URL
    import asyncpg
    
    start_time = datetime.now()
    conn = None
    log_id = None
    
    # Initialize status
    import_status["baseball"] = {
        "status": "running",
        "started_at": start_time.isoformat(),
        "completed_at": None,
        "progress": [f"D{division} {year} import started..."],
        "result": None,
        "error": None
    }
    
    try:
        # 1. Create DB log
        conn = await asyncpg.connect(DATABASE_URL)
        log_id = await conn.fetchval("""
            INSERT INTO import_logs (sport, status, start_time)
            VALUES ('baseball', 'IN_PROGRESS', NOW())
            RETURNING id
        """)
        
        # 2. Run import
        result = await run_college_baseball_import(division, year, team_id, source)
        
        # 3. Handle result
        rows = result.get("rows", 0)
        status = "COMPLETED" if result.get("success") else "FAILED"
        
        import_status["baseball"]["status"] = status.lower()
        import_status["baseball"]["completed_at"] = datetime.now().isoformat()
        import_status["baseball"]["result"] = result
        
        # 4. Update DB log
        duration = (datetime.now() - start_time).total_seconds()
        error_msg = result.get("message") if not result.get("success") else None
        
        await conn.execute("""
            UPDATE import_logs 
            SET status = $2, end_time = NOW(), duration_seconds = $3, 
                rows_imported = $4, error_message = $5
            WHERE id = $1
        """, log_id, status, duration, rows, error_msg)
        
    except Exception as e:
        logger.error(f"Baseball import failed: {e}")
        import_status["baseball"]["status"] = "failed"
        import_status["baseball"]["error"] = str(e)
        if conn and log_id:
            duration = (datetime.now() - start_time).total_seconds()
            await conn.execute("""
                UPDATE import_logs 
                SET status = 'FAILED', end_time = NOW(), duration_seconds = $2, 
                    error_message = $3
                WHERE id = $1
            """, log_id, duration, str(e))
    finally:
        if conn:
            await conn.close()


@app.post('/baseball/ncaa/import')
async def import_college_baseball(
    division: int = Query(0, description="NCAA Division (1, 2, or 3). Use 0 for ALL divisions (default: one-click import)"),
    year: int = Query(0, description="Season year. Use 0 for smart year detection (default: auto-detect based on season calendar)"),
    team_id: Optional[int] = Query(None, description="Optional specific team ID"),
    source: str = Query("auto", description="Data source: auto, python (ncaa_bbStats), r (baseballr), both"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    One-click dynamic college baseball importer.
    
    This endpoint automatically:
    - Detects the appropriate season year (smart year detection)
    - Imports all divisions in priority order (D1, D3, D2)
    - Falls back to previous years for D2 if current year fails
    
    Reference packages:
    - Python: https://github.com/JohnJustinn/ncaa-bbStats
    - R: https://github.com/BillPetti/baseballr
    """
    try:
        year_desc = "smart detection" if year == 0 else str(year)
        div_desc = "ALL" if division == 0 else f"D{division}"
        logger.info(f"Starting dynamic college baseball import: {div_desc}, Year: {year_desc}, Source: {source}")
        
        # Run in background with logging wrapper (year=0 triggers smart detection in importer)
        background_tasks.add_task(run_baseball_import_with_logging, division, year if year != 0 else None, team_id, source)
        
        return {
            "status": "started", 
            "message": f"One-click import started for {div_desc}, Year: {year_desc}",
            "division": division,
            "year": year,
            "smart_year": year == 0,
            "all_divisions": division == 0
        }
    except Exception as e:
        logger.error(f"Error starting import: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/baseball/ncaa/status')
def get_college_baseball_status():
    """Get current status of college baseball import."""
    try:
        from scripts.college_baseball_importer import get_import_status
        return get_import_status()
    except Exception as e:
        return {"status": "error", "message": str(e)}




@app.get('/baseball/ncaa/schedule/{team_id}')
def get_college_baseball_schedule(team_id: str, year: int = Query(2025, description="Season year")):
    """Get schedule/results for a team."""
    """Get schedule/results for a team. team_id can be string like 'LSU__SEC'."""
    try:
        from scripts.college_baseball_importer import get_team_schedule
        # team_id can be string (e.g., 'LSU__SEC') or numeric string
        schedule = get_team_schedule(team_id, year=year)
        return {
            "team_id": team_id,
            "year": year,
            "games": schedule or [],
            "count": len(schedule) if schedule else 0
        }
    except Exception as e:
        logger.error(f"Error getting schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/baseball/ncaa/summary')
def get_college_baseball_summary(division: int = 1):
    """Get import summary for a division."""
    try:
        from scripts.college_baseball_importer import get_import_summary
        summary = get_import_summary(division)
        if summary:
            return summary
        return {"error": True, "message": f"No import summary found for D{division}"}
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/logs')
def get_system_logs(level: str = None, limit: int = 100):
    '''Get recent system logs for the Logs Dashboard.'''
    logs = get_logs(level, limit)
    return {"logs": logs, "total": len(LOG_BUFFER), "showing": len(logs)}


# ========== Model Testing Endpoints ==========

@app.post('/model-testing/nba/predictions')
async def get_nba_model_testing_predictions(
    sportsbook: str = Query("fanduel", description="Sportsbook for odds")
):
    """
    Get today's NBA games with BOTH simple and kyleskom XGBoost predictions.
    Uses kyleskom's pre-trained model (68.9% accuracy) and full NBA API data.
    """
    try:
        from scripts.nba_odds import get_todays_nba_odds
        from scripts.model_testing_predictor import predict_nba_simple, get_nba_team_stats
        from scripts.kyleskom_adapter import predict_with_kyleskom, normalize_team_name
        
        # Get today's games with odds
        odds_data = await get_todays_nba_odds(sportsbook)
        
        if odds_data.get("error") or not odds_data.get("games"):
            return odds_data
        
        # Get all team stats for simple model
        all_team_stats = await get_nba_team_stats()
        
        analyzed_games = []
        for game in odds_data["games"]:
            # Log original team names from sbrscrape for debugging
            original_home = game.get("home_team", "")
            original_away = game.get("away_team", "")
            
            # Normalize team names to handle variations like "LA Clippers" -> "Los Angeles Clippers"
            home_team = normalize_team_name(original_home)
            away_team = normalize_team_name(original_away)
            
            # Log if normalization changed anything
            if home_team != original_home or away_team != original_away:
                logger.info(f"Team name normalization: '{original_home}' -> '{home_team}', '{original_away}' -> '{away_team}'")
            
            home_ml = game.get("home_moneyline")
            away_ml = game.get("away_moneyline")
            total_line = game.get("over_under") or game.get("total", 225.0)
            
            # Use normalized names for stats lookup too
            home_stats = all_team_stats.get(home_team, {})
            away_stats = all_team_stats.get(away_team, {})
            
            # Get prediction from simple model
            simple_pred = await predict_nba_simple(
                home_team, away_team, home_stats, away_stats, home_ml, away_ml
            )
            
            # Get prediction from kyleskom's pre-trained model (68.9% accuracy)
            kyleskom_pred = await predict_with_kyleskom(
                home_team, away_team, total_line, home_ml, away_ml
            )
            
            # Log kyleskom prediction result for debugging
            if kyleskom_pred.get("error"):
                logger.warning(f"Kyleskom prediction error for {home_team} vs {away_team}: {kyleskom_pred.get('error')}")
            analyzed_games.append({
                **game,
                "simple_model": simple_pred,
                "xgboost_model": kyleskom_pred,  # Now using kyleskom's model
                "home_stats": home_stats,
                "away_stats": away_stats,
            })
        
        return {
            "date": odds_data.get("date"),
            "sportsbook": sportsbook,
            "games": analyzed_games,
            "count": len(analyzed_games),
            "xgb_model_source": "kyleskom/NBA-Machine-Learning-Sports-Betting",
            "xgb_model_accuracy": "68.9%",
        }
        
    except Exception as e:
        logger.error(f"Model testing NBA error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/model-testing/nfl/predictions')
async def get_nfl_model_testing_predictions(
    sportsbook: str = Query("fanduel", description="Sportsbook for odds")
):
    """
    Get today's NFL games with BOTH simple and nflverse XGBoost predictions.
    Uses nflverse data (EPA, success rate, etc.) with no hardcoded values.
    """
    try:
        # Force reload check
        from scripts.nfl_predictor import get_todays_nfl_odds
        from scripts.nflverse_adapter import predict_with_nflverse, get_nflverse_predictor
        from scripts.model_testing_predictor import predict_nfl_simple
        
        # Get today's games with odds
        odds_data = await get_todays_nfl_odds(sportsbook)
        
        if odds_data.get("error") or not odds_data.get("games"):
            return odds_data
        
        # Pre-fetch nflverse stats
        predictor = get_nflverse_predictor()
        await predictor.fetch_team_stats_from_nflverse()
        
        analyzed_games = []
        for game in odds_data["games"]:
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")
            home_ml = game.get("home_moneyline")
            away_ml = game.get("away_moneyline")
            total_line = game.get("over_under") or game.get("total", 45.0)
            
            # Get stats from nflverse
            home_stats = predictor.team_stats.get(home_team, {})
            away_stats = predictor.team_stats.get(away_team, {})
            
            # Get prediction from simple model
            simple_pred = await predict_nfl_simple(
                home_team, away_team, home_stats, away_stats, home_ml, away_ml
            )
            
            # Get prediction from nflverse model (uses real EPA data)
            nflverse_pred = await predict_with_nflverse(
                home_team, away_team, total_line, home_ml, away_ml
            )
            
            analyzed_games.append({
                **game,
                "simple_model": simple_pred,
                "xgboost_model": nflverse_pred,  # Now using nflverse data
                "home_stats": home_stats,
                "away_stats": away_stats,
            })
        
        return {
            "date": odds_data.get("date"),
            "sportsbook": sportsbook,
            "games": analyzed_games,
            "count": len(analyzed_games),
            "data_source": odds_data.get("source", "nflverse"),
            "api_quota": odds_data.get("api_quota"),
        }
        
    except Exception as e:
        logger.error(f"Model testing NFL error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== COLLEGE BASEBALL ENDPOINTS ====================

@app.get("/baseball/ncaa/teams")
async def get_ncaa_baseball_teams(
    division: int = Query(1, ge=1, le=3),
    year: Optional[int] = Query(None, description="Optional - only used if fetching fresh data from NCAA")
):
    """
    Get list of NCAA baseball teams for a division.
    Division: 1, 2, or 3
    Year is optional - teams are mostly static, year only matters for fresh imports.
    """
    try:
        from scripts.college_baseball_importer import get_teams, get_import_summary
        import subprocess
        import json
        from pathlib import Path
        
        # Default year for R calls if needed
        fetch_year = year or 2025
        
        # Check if teams file exists
        teams = get_teams(division)
        
        if not teams:
            # Try to fetch teams using R script
            logger.info(f"No cached teams for D{division}, running import with year={fetch_year}...")
            
            r_script = Path(__file__).parent.parent / "scripts" / "college_baseball_importer.R"
            data_dir = Path("/app/data/baseball")
            data_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                result = subprocess.run(
                    ["Rscript", str(r_script), str(division), str(fetch_year), str(data_dir)],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    teams = get_teams(division)
            except subprocess.TimeoutExpired:
                logger.warning("R script timed out")
            except Exception as e:
                logger.warning(f"R script error: {e}")
        
        # If still no teams, try direct baseballr call
        if not teams:
            logger.info("Falling back to direct baseballr call...")
            try:
                import subprocess
                result = subprocess.run(
                    ["Rscript", "-e", f"library(baseballr); teams <- ncaa_teams(division={division}, year={fetch_year}); cat(jsonlite::toJSON(teams))"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode == 0 and result.stdout:
                    teams = json.loads(result.stdout)
            except Exception as e:
                logger.error(f"Direct R call failed: {e}")
        
        # Format teams for frontend
        formatted_teams = []
        for team in teams:
            formatted_teams.append({
                "TeamId": team.get("team_id") or team.get("school_id") or "",
                "TeamName": team.get("ncaa_name") or team.get("team_name") or team.get("school") or "",
                "Conference": team.get("conference", ""),
                "Division": division
            })
        
        summary = get_import_summary(division)
        
        return {
            "division": division,
            "teams": formatted_teams,
            "count": len(formatted_teams),
            "last_import": summary.get("generated_at") if summary else None
        }
        
    except Exception as e:
        logger.error(f"Error fetching NCAA teams: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/baseball/ncaa/stats/{team_id}")
async def get_ncaa_baseball_stats(
    team_id: str, 
    stat_type: str = Query("batting"),
    year: int = Query(2025, description="Season year")
):
    """
    Get player stats for a team.
    stat_type: 'batting' or 'pitching'
    """
    try:
        from scripts.college_baseball_importer import get_team_player_stats, get_team_stats
        
        # team_id can be string (e.g., 'LSU__SEC') or numeric string
        # get_team_player_stats now has internal on-demand fallback via R script
        stats = get_team_player_stats(str(team_id), stat_type, year=year)
        
        
        return {
            "team_id": team_id,
            "stat_type": stat_type,
            "stats": stats or [],
            "count": len(stats) if stats else 0
        }
        
    except Exception as e:
        logger.error(f"Error fetching team stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Duplicate schedule endpoint removed - consolidated with /baseball/ncaa/schedule/{team_id} above




# ==================== NBA_AI PREDICTIONS ====================

@app.get("/nba/ai/predictions")
async def get_nba_ai_predictions(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    home_ppg: float = Query(110.0, description="Home team PPG"),
    away_ppg: float = Query(108.0, description="Away team PPG"),
    home_fg_pct: float = Query(0.47, description="Home team FG%"),
    away_fg_pct: float = Query(0.46, description="Away team FG%")
):
    """
    Get predictions from all NBA_AI engines.
    
    Returns predictions from: Baseline, Linear, Tree, MLP, Ensemble
    """
    try:
        from scripts.nba_ai_adapter import get_nba_ai_predictions as ai_predict
        
        home_stats = {
            "team_name": home_team,
            "pts_per_game": home_ppg,
            "fg_pct": home_fg_pct
        }
        away_stats = {
            "team_name": away_team,
            "pts_per_game": away_ppg,
            "fg_pct": away_fg_pct
        }
        
        return ai_predict(home_stats, away_stats)
        
    except Exception as e:
        logger.error(f"Error getting NBA AI predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nba/ai/engines")
async def get_nba_ai_engines():
    """List available NBA_AI prediction engines."""
    return {
        "engines": [
            {"name": "Baseline", "description": "Simple PPG-based predictor", "confidence": "low"},
            {"name": "Linear", "description": "Ridge Regression with rolling features", "confidence": "medium"},
            {"name": "Tree", "description": "XGBoost model", "confidence": "high"},
            {"name": "MLP", "description": "PyTorch neural network", "confidence": "medium"},
            {"name": "Ensemble", "description": "Weighted average: 30% Linear + 40% Tree + 30% MLP", "confidence": "high"}
        ],
        "source": "https://github.com/NBA-Betting/NBA_AI"
    }


# ==================== NBA SEASON SIMULATION (Monte Carlo) ====================

@app.post("/nba/simulation/season")
async def run_nba_season_simulation(
    num_simulations: int = Query(1000, description="Number of simulations to run (100-10000)")
):
    """
    Run Monte Carlo simulation of remaining NBA season.
    
    Based on: https://github.com/matsonj/nba-monte-carlo
    
    Returns playoff odds, seed distributions, and win projections for each team.
    """
    try:
        from scripts.nba_season_simulator import run_nba_season_simulation as run_sim
        
        # Clamp simulations to reasonable range
        num_simulations = max(100, min(10000, num_simulations))
        
        logger.info(f"Running NBA season simulation with {num_simulations} iterations")
        results = run_sim(num_simulations=num_simulations)
        
        return results
        
    except Exception as e:
        logger.error(f"Error running NBA season simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nba/simulation/status")
async def get_nba_simulation_status():
    """Check if NBA simulation is available."""
    try:
        from scripts.nba_season_simulator import NBA_API_AVAILABLE
        return {
            "available": True,
            "nba_api_available": NBA_API_AVAILABLE,
            "description": "Monte Carlo NBA season simulator",
            "source": "https://github.com/matsonj/nba-monte-carlo"
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


# ============== NBA_AI INTEGRATION ENDPOINTS ==============

@app.get("/nba/ai/integration/status")
async def get_nba_ai_integration_status():
    """Get status of NBA_AI integration from cloned repo."""
    try:
        from scripts.nba_ai_integration import get_integration_status
        return get_integration_status()
    except Exception as e:
        logger.error(f"Error getting NBA_AI integration status: {e}")
        return {"status": "error", "error": str(e)}


@app.get("/nba/ai/integration/predictions")
async def get_nba_ai_all_predictions(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    home_ppg: float = Query(110.0, description="Home team PPG"),
    away_ppg: float = Query(108.0, description="Away team PPG"),
    home_opp_ppg: float = Query(112.0, description="Home team opponent PPG"),
    away_opp_ppg: float = Query(112.0, description="Away team opponent PPG"),
    home_fg_pct: float = Query(0.47, description="Home team FG%"),
    away_fg_pct: float = Query(0.46, description="Away team FG%"),
    home_win_pct: float = Query(0.5, description="Home team win%"),
    away_win_pct: float = Query(0.5, description="Away team win%")
):
    """
    Get predictions from all 5 NBA_AI engines.
    
    Uses the cloned NBA_AI repo (https://github.com/NBA-Betting/NBA_AI).
    Engines: Baseline, Linear, Tree, MLP, Ensemble
    """
    try:
        from scripts.nba_ai_integration import get_all_predictions
        
        home_stats = {
            "pts_per_game": home_ppg,
            "opp_pts_per_game": home_opp_ppg,
            "fg_pct": home_fg_pct,
            "win_pct": home_win_pct,
            "pace": 100
        }
        away_stats = {
            "pts_per_game": away_ppg,
            "opp_pts_per_game": away_opp_ppg,
            "fg_pct": away_fg_pct,
            "win_pct": away_win_pct,
            "pace": 100
        }
        
        return get_all_predictions(home_team, away_team, home_stats, away_stats)
    except Exception as e:
        logger.error(f"Error getting NBA_AI predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/nba/ai/integration/live")
async def get_nba_ai_live_prediction(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    current_home_score: int = Query(..., description="Current home score"),
    current_away_score: int = Query(..., description="Current away score"),
    period: int = Query(..., description="Current period (1-4, 5+ for OT)"),
    time_remaining: str = Query(..., description="Time remaining in period (MM:SS)")
):
    """
    Get live in-game prediction updates.
    
    Uses NBA_AI's blending formula to update predictions based on:
    - Pre-game prediction
    - Current score
    - Time remaining
    
    Credit: https://github.com/NBA-Betting/NBA_AI
    """
    try:
        from scripts.nba_ai_integration import get_live_prediction_update
        
        return get_live_prediction_update(
            home_team=home_team,
            away_team=away_team,
            current_home_score=current_home_score,
            current_away_score=current_away_score,
            period=period,
            time_remaining=time_remaining
        )
    except Exception as e:
        logger.error(f"Error getting live NBA_AI prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/nba/ai/integration/train")
async def train_nba_ai_models(
    model_type: str = Query("all", description="Model type: Linear, Tree, MLP, or all"),
    train_season: str = Query("2023-2024", description="Training season"),
    test_season: str = Query("2024-2025", description="Test season")
):
    """
    Train NBA_AI prediction models.
    
    This runs the NBA_AI training pipeline to train:
    - Linear (Ridge Regression)
    - Tree (XGBoost)
    - MLP (PyTorch Neural Network)
    
    Requires the NBA_AI database to be present.
    Credit: https://github.com/NBA-Betting/NBA_AI
    """
    try:
        from scripts.nba_ai_integration import run_nba_ai_training
        
        result = run_nba_ai_training(
            model_type=model_type,
            train_season=train_season,
            test_season=test_season
        )
        return result
    except Exception as e:
        logger.error(f"Error training NBA_AI models: {e}")
        raise HTTPException(status_code=500, detail=str(e))





# ============== NBA SEASON SIMULATION ENDPOINTS ==============

@app.post("/nba/simulation/season")
async def run_nba_season_sim(
    num_simulations: int = Query(1000, description="Number of Monte Carlo simulations")
):
    """
    Run Monte Carlo simulation of NBA season.
    Returns playoff probabilities and seed distributions for each team.
    """
    try:
        from scripts.nba_season_simulator import run_nba_season_simulation
        result = run_nba_season_simulation(num_simulations)
        return result
    except Exception as e:
        logger.error(f"Error running NBA season simulation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nba/simulation/standings")
async def get_nba_standings():
    """Get current NBA standings for simulation."""
    try:
        from scripts.nba_season_simulator import NBASeasonSimulator
        simulator = NBASeasonSimulator()
        standings = simulator.load_current_standings()
        return {"standings": standings}
    except Exception as e:
        logger.error(f"Error getting NBA standings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== NFL COMPREHENSIVE DATA ENDPOINTS ==============

@app.post("/nfl/data/download-comprehensive")
async def download_nfl_comprehensive_data():
    """
    Download comprehensive nflverse datasets including:
    - Next Gen Stats (passing, rushing, receiving)
    - Snap Counts
    - Combine Data
    - Draft Picks
    - Injuries (historical)
    - Contracts
    - PFR Advanced Stats
    """
    try:
        from scripts.nfl_importer import download_comprehensive_nflverse
        result = await download_comprehensive_nflverse()
        return {
            "status": "complete",
            "datasets": result
        }
    except Exception as e:
        logger.error(f"Error downloading comprehensive nflverse data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/data/status")
async def get_nfl_data_status():
    """Check which nflverse datasets are available locally and their timestamps."""
    from pathlib import Path
    import os
    from datetime import datetime
    
    NFLVERSE_DIR = Path("/app/data/nflverse")
    NGS_DIR = NFLVERSE_DIR / "nextgen_stats"
    ADVANCED_DIR = NFLVERSE_DIR / "advanced_stats"
    
    def get_file_info(path: Path):
        exists = path.exists()
        timestamp = None
        if exists:
            try:
                mtime = os.path.getmtime(path)
                timestamp = datetime.fromtimestamp(mtime).isoformat()
            except:
                pass
        return {"exists": exists, "timestamp": timestamp}
    
    status = {
        "nextgen_stats": {
            "passing": get_file_info(NGS_DIR / "ngs_passing.parquet"),
            "rushing": get_file_info(NGS_DIR / "ngs_rushing.parquet"),
            "receiving": get_file_info(NGS_DIR / "ngs_receiving.parquet"),
        },
        "snap_counts": get_file_info(NFLVERSE_DIR / "snap_counts.parquet"),
        "combine": get_file_info(NFLVERSE_DIR / "combine.parquet"),
        "draft_picks": get_file_info(NFLVERSE_DIR / "draft_picks.parquet"),
        "teams": get_file_info(NFLVERSE_DIR / "teams.parquet"),
        "injuries": get_file_info(NFLVERSE_DIR / "injuries.parquet"),
        "contracts": get_file_info(NFLVERSE_DIR / "historical_contracts.parquet"),
        "advanced_stats": {
            "passing": get_file_info(ADVANCED_DIR / "advstats_season_pass.parquet"),
            "rushing": get_file_info(ADVANCED_DIR / "advstats_season_rush.parquet"),
            "receiving": get_file_info(ADVANCED_DIR / "advstats_season_rec.parquet"),
            "defense": get_file_info(ADVANCED_DIR / "advstats_season_def.parquet"),
        },
        "basic": {
            "players": get_file_info(NFLVERSE_DIR / "players.csv"),
            "schedules": get_file_info(NFLVERSE_DIR / "schedules.csv"),
            "rosters": get_file_info(NFLVERSE_DIR / "roster.csv"),
        }
    }
    
    return {"datasets": status}


@app.get("/nfl/ngs")
async def get_nfl_ngs(
    season: int = Query(None, description="Filter by season"),
    category: str = Query("passing", description="Category: passing, rushing, or receiving"),
    limit: int = Query(50, description="Max results to return")
):
    """
    Unified Next Gen Stats endpoint for leaderboards.
    Routes to appropriate category handler based on parameter.
    """
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        category = category.lower()
        file_map = {
            "passing": "ngs_passing.parquet",
            "rushing": "ngs_rushing.parquet", 
            "receiving": "ngs_receiving.parquet"
        }
        
        if category not in file_map:
            return {"error": f"Invalid category: {category}. Use passing, rushing, or receiving."}
        
        file_path = Path(f"/app/data/nflverse/nextgen_stats/{file_map[category]}")
        if not file_path.exists():
            return {"error": f"NGS {category} data not downloaded yet", "download": "/nfl/data/download-comprehensive"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        # Apply season filter
        if season and 'season' in df.columns:
            df = df[df['season'] == season]
        
        # Sort by relevant metric for leaderboard
        sort_cols = {
            "passing": "passing_yards",
            "rushing": "rushing_yards",
            "receiving": "receiving_yards"
        }
        if sort_cols[category] in df.columns:
            df = df.sort_values(sort_cols[category], ascending=False)
        
        return df.head(limit).to_dict(orient='records')
        
    except Exception as e:
        logger.error(f"Error in /nfl/ngs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/nextgen/passing")
async def get_nfl_ngs_passing(
    season: int = Query(None, description="Filter by season"),
    week: int = Query(None, description="Filter by week"),
    player: str = Query(None, description="Filter by player name"),
    team: str = Query(None, description="Filter by team abbreviation")
):
    """Get Next Gen Stats for passing."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/nextgen_stats/ngs_passing.parquet")
        if not file_path.exists():
            return {"error": "Next Gen passing stats not downloaded yet", "download": "/nfl/data/download-comprehensive"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        # Apply filters
        if season:
            df = df[df['season'] == season]
        if week:
            df = df[df['week'] == week]
        if team:
            df = df[df['team_abbr'].str.upper() == team.upper()]
        if player:
            df = df[df['player_display_name'].str.contains(player, case=False, na=False)]
        
        # Sort by key metrics
        if 'avg_time_to_throw' in df.columns:
            df = df.sort_values('avg_time_to_throw', ascending=True)
        
        return {
            "count": len(df),
            "data": df.head(100).to_dict(orient='records')
        }
    except Exception as e:
        logger.error(f"Error reading NGS passing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/nextgen/rushing")
async def get_nfl_ngs_rushing(
    season: int = Query(None),
    week: int = Query(None),
    player: str = Query(None),
    team: str = Query(None)
):
    """Get Next Gen Stats for rushing."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/nextgen_stats/ngs_rushing.parquet")
        if not file_path.exists():
            return {"error": "Next Gen rushing stats not downloaded yet"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        if season:
            df = df[df['season'] == season]
        if week:
            df = df[df['week'] == week]
        if team:
            df = df[df['team_abbr'].str.upper() == team.upper()]
        if player:
            df = df[df['player_display_name'].str.contains(player, case=False, na=False)]
        
        return {"count": len(df), "data": df.head(100).to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/nextgen/receiving")
async def get_nfl_ngs_receiving(
    season: int = Query(None),
    week: int = Query(None),
    player: str = Query(None),
    team: str = Query(None)
):
    """Get Next Gen Stats for receiving."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/nextgen_stats/ngs_receiving.parquet")
        if not file_path.exists():
            return {"error": "Next Gen receiving stats not downloaded yet"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        if season:
            df = df[df['season'] == season]
        if week:
            df = df[df['week'] == week]
        if team:
            df = df[df['team_abbr'].str.upper() == team.upper()]
        if player:
            df = df[df['player_display_name'].str.contains(player, case=False, na=False)]
        
        return {"count": len(df), "data": df.head(100).to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/snap-counts")
async def get_nfl_snap_counts(
    season: int = Query(None),
    week: int = Query(None),
    team: str = Query(None),
    player: str = Query(None)
):
    """Get snap count data for players."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/snap_counts.parquet")
        if not file_path.exists():
            return {"error": "Snap counts not downloaded yet"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        if season:
            df = df[df['season'] == season]
        if week:
            df = df[df['week'] == week]
        if team:
            df = df[df['team'].str.upper() == team.upper()]
        if player:
            df = df[df['player'].str.contains(player, case=False, na=False)]
        
        return {"count": len(df), "data": df.head(100).to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/combine")
async def get_nfl_combine(
    position: str = Query(None, description="Filter by position (QB, RB, WR, etc.)"),
    year: int = Query(None, description="Draft year"),
    team: str = Query(None)
):
    """Get NFL Combine data."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/combine.parquet")
        if not file_path.exists():
            return {"error": "Combine data not downloaded yet"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        if position:
            df = df[df['pos'].str.upper() == position.upper()]
        if year:
            df = df[df['draft_year'] == year]
        if team:
            df = df[df['team'].str.upper() == team.upper()]
        
        # Sort by 40 time for skill positions
        if 'forty' in df.columns:
            df = df.sort_values('forty', ascending=True)
        
        return {"count": len(df), "data": df.head(100).to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/draft")
async def get_nfl_draft_picks(
    season: int = Query(None, description="Draft year"),
    team: str = Query(None, description="Team abbreviation"),
    position: str = Query(None, description="Position")
):
    """Get NFL Draft Picks data."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/draft_picks.parquet")
        if not file_path.exists():
            return {"error": "Draft picks data not downloaded yet"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        if season:
            df = df[df['season'] == season]
        if team:
            df = df[df['team'].str.upper() == team.upper()]
        if position:
            df = df[df['position'].str.upper() == position.upper()]
            
        return {"count": len(df), "data": df.head(100).to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/injuries")
async def get_nfl_injuries(
    season: int = Query(None, description="Season"),
    team: str = Query(None, description="Team abbreviation"),
    player: str = Query(None, description="Player name")
):
    """Get NFL Injuries data."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/injuries.parquet")
        if not file_path.exists():
            return {"error": "Injuries data not downloaded yet", "data": []}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        # Handle column name variations
        if season:
            if 'season' in df.columns:
                df = df[df['season'] == season]
        if team:
            team_col = next((c for c in ['team', 'team_abbr', 'club_code'] if c in df.columns), None)
            if team_col:
                df = df[df[team_col].str.upper() == team.upper()]
        if player:
            name_col = next((c for c in ['full_name', 'name', 'player', 'player_name'] if c in df.columns), None)
            if name_col:
                df = df[df[name_col].str.contains(player, case=False, na=False)]
            
        return {"count": len(df), "data": df.head(100).to_dict(orient='records'), "columns": list(df.columns)}
    except Exception as e:
        logger.error(f"Error loading injuries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/contracts")
async def get_nfl_contracts(
    team: str = Query(None, description="Team abbreviation"),
    player: str = Query(None, description="Player name"),
    position: str = Query(None, description="Position")
):
    """Get NFL Contracts data."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/historical_contracts.parquet")
        if not file_path.exists():
            return {"error": "Contracts data not downloaded yet", "data": []}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        # Handle column name variations
        if team:
            team_col = next((c for c in ['team', 'team_abbr', 'club'] if c in df.columns), None)
            if team_col:
                df = df[df[team_col].str.upper() == team.upper()]
        if player:
            name_col = next((c for c in ['player', 'player_name', 'name', 'full_name'] if c in df.columns), None)
            if name_col:
                df = df[df[name_col].str.contains(player, case=False, na=False)]
        if position:
            pos_col = next((c for c in ['position', 'pos'] if c in df.columns), None)
            if pos_col:
                df = df[df[pos_col].str.upper() == position.upper()]
            
        return {"count": len(df), "data": df.head(100).to_dict(orient='records'), "columns": list(df.columns)}
    except Exception as e:
        logger.error(f"Error loading contracts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/teams")
async def get_nfl_teams():
    """Get NFL Teams metadata."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        file_path = Path("/app/data/nflverse/teams.parquet")
        if not file_path.exists():
            return {"error": "Teams data not downloaded yet"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        return {"count": len(df), "data": df.head(100).to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/advanced/{category}")
async def get_nfl_advanced_stats(
    category: str,
    season: int = Query(None, description="Season"),
    team: str = Query(None, description="Team abbreviation")
):
    """Get PFR Advanced Stats (passing, rushing, receiving, defense)."""
    try:
        import pyarrow.parquet as pq
        from pathlib import Path
        
        # Map category to filename (PFR Advanced Stats - using nflverse source naming)
        file_map = {
            "passing": "advstats_season_pass.parquet",
            "rushing": "advstats_season_rush.parquet",
            "receiving": "advstats_season_rec.parquet",
            "defense": "advstats_season_def.parquet"
        }
        
        if category not in file_map:
            raise HTTPException(status_code=400, detail="Invalid category. Use: passing, rushing, receiving, defense")
            
        file_path = Path(f"/app/data/nflverse/advanced_stats/{file_map[category]}")
        if not file_path.exists():
            return {"error": f"Advanced {category} stats not downloaded yet"}
        
        table = pq.read_table(file_path)
        df = table.to_pandas()
        
        if season:
            df = df[df['season'] == season]
        if team:
            df = df[df['team'].str.upper() == team.upper()]
            
        return {"count": len(df), "data": df.head(100).to_dict(orient='records')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== APEX MODEL ENDPOINTS ====================

@app.get("/apex/predict/nba")
async def apex_predict_nba(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    total_line: float = Query(225.0, description="O/U line"),
    home_ml: int = Query(None, description="Home moneyline odds"),
    away_ml: int = Query(None, description="Away moneyline odds")
):
    """Predict NBA game using Apex model."""
    try:
        from scripts.apex_model import predict_nba_apex
        return await predict_nba_apex(home_team, away_team, total_line, home_ml, away_ml)
    except Exception as e:
        logger.error(f"Apex NBA prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/apex/predict/nfl")
async def apex_predict_nfl(
    home_team: str = Query(..., description="Home team abbreviation"),
    away_team: str = Query(..., description="Away team abbreviation"),
    total_line: float = Query(45.0, description="O/U line"),
    home_ml: int = Query(None, description="Home moneyline odds"),
    away_ml: int = Query(None, description="Away moneyline odds")
):
    """Predict NFL game using Apex model."""
    try:
        from scripts.apex_model import predict_nfl_apex
        return await predict_nfl_apex(home_team, away_team, total_line, home_ml, away_ml)
    except Exception as e:
        logger.error(f"Apex NFL prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/apex/train")
async def apex_train(
    sport: str = Query("all", description="Sport to train: nba, nfl, or all"),
    epochs: int = Query(500, description="Training epochs")
):
    """Train Apex model for specified sport(s)."""
    try:
        from scripts.apex_trainer import train_apex_nba, train_apex_nfl, train_apex_all
        
        if sport.lower() == "nba":
            return await train_apex_nba(epochs)
        elif sport.lower() == "nfl":
            return await train_apex_nfl(epochs)
        else:
            return await train_apex_all(epochs)
    except Exception as e:
        logger.error(f"Apex training error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/apex/status")
async def apex_status():
    """Get Apex model training status and info."""
    try:
        from scripts.apex_model import get_apex_predictor
        predictor = get_apex_predictor()
        return predictor.get_model_info()
    except Exception as e:
        logger.error(f"Apex status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/apex/compare/nba")
async def apex_compare_nba(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    total_line: Optional[float] = Query(None, description="O/U line"),
    home_ml: Optional[int] = Query(None, description="Home moneyline odds"),
    away_ml: Optional[int] = Query(None, description="Away moneyline odds")
):
    """Compare all 3 models (Simple, Kyle, Apex) for NBA prediction."""
    try:
        results = {"home_team": home_team, "away_team": away_team, "models": {}}
        
        # 1. Simple model (basic rolling averages)
        try:
            from scripts.nba_simple_predictor import predict_simple
            simple_result = await predict_simple(home_team, away_team)
            results["models"]["simple"] = simple_result if simple_result else {"error": "Not available"}
        except Exception as e:
            results["models"]["simple"] = {"error": str(e)}
        
        # 2. Kyle model (kyleskom's XGBoost)
        try:
            from scripts.kyleskom_adapter import predict_with_kyleskom
            kyle_result = await predict_with_kyleskom(home_team, away_team, total_line, home_ml, away_ml)
            results["models"]["kyle"] = kyle_result
        except Exception as e:
            results["models"]["kyle"] = {"error": str(e)}
        
        # 3. Apex model (our enhanced)
        try:
            from scripts.apex_model import predict_nba_apex
            apex_result = await predict_nba_apex(home_team, away_team, total_line, home_ml, away_ml)
            results["models"]["apex"] = apex_result
        except Exception as e:
            results["models"]["apex"] = {"error": str(e)}
        
        return results
    except Exception as e:
        logger.error(f"Model comparison error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/apex/compare/ncaab")
async def apex_compare_ncaab(
    home_team: str = Query(..., description="Home team name"),
    away_team: str = Query(..., description="Away team name"),
    total_line: Optional[float] = Query(None, description="O/U line"),
    home_ml: Optional[int] = Query(None, description="Home moneyline odds"),
    away_ml: Optional[int] = Query(None, description="Away moneyline odds")
):
    """Compare models (Simple, XGBoost v2, ESPN BPI) for NCAAB prediction."""
    try:
        from scripts.ncaab_predictor import NCAABPredictor
        predictor = NCAABPredictor()
        
        results = {"home_team": home_team, "away_team": away_team, "models": {}}
        
        # 1. Internal Models (Simple + XGB v2)
        prediction = predictor.predict_game(home_team, away_team, spread=None, over_under=total_line)
        
        results["models"]["simple"] = {
            "win_prob": prediction.get("home_win_probability"),
            "total": prediction.get("predicted_total"),
            "winner": prediction.get("predicted_winner")
        }
        
        if prediction.get("v2_available"):
            results["models"]["xgb"] = {
                "win_prob": prediction.get("v2_win_prob"),
                "total": prediction.get("v2_total"),
                "winner": prediction.get("v2_winner")
            }
        
        # 2. ESPN BPI Integration
        try:
            from api.espn_endpoints import get_espn_ncaab_predictions
            espn_data = await get_espn_ncaab_predictions()
            
            # Simple team matcher
            def normalize(n): return n.lower().replace(" state", " st").replace(" university", "").strip()
            
            h_norm = normalize(home_team)
            a_norm = normalize(away_team)
            
            espn_match = None
            for game in espn_data.get("games", []):
                e_home = normalize(game.get("home_team", ""))
                e_away = normalize(game.get("away_team", ""))
                
                if (h_norm in e_home or e_home in h_norm) and (a_norm in e_away or e_away in a_norm):
                    espn_match = game
                    break
            
            if espn_match and espn_match.get("has_bpi"):
                results["models"]["espn"] = {
                    "win_prob": espn_match.get("home_win_prob"),
                    "total_over_prob": espn_match.get("total_over_prob"),
                    "winner": home_team if espn_match.get("home_win_prob") > 0.5 else away_team
                }
        except Exception as e:
            logger.warning(f"Could not fetch ESPN BPI for NCAAB comparison: {e}")

        return results
    except Exception as e:
        logger.error(f"NCAAB Model comparison error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/apex/compare/nfl")
async def apex_compare_nfl(
    home_team: str = Query(..., description="Home team abbreviation"),
    away_team: str = Query(..., description="Away team abbreviation"),
    total_line: float = Query(45.0, description="O/U line"),
    home_ml: int = Query(None, description="Home moneyline odds"),
    away_ml: int = Query(None, description="Away moneyline odds")
):
    """Compare Simple and Apex models for NFL prediction (Kyle is NBA-only)."""
    try:
        results = {"home_team": home_team, "away_team": away_team, "models": {}}
        
        # 1. Simple model (existing NFL XGBoost)
        try:
            from scripts.nfl_xgb_trainer import predict_nfl_xgb
            # Get basic stats for prediction
            simple_result = await predict_nfl_xgb(home_team, away_team, {}, {})
            results["models"]["simple"] = simple_result if simple_result else {"error": "Not available"}
        except Exception as e:
            results["models"]["simple"] = {"error": str(e)}
        
        # 2. Kyle model - NOT available for NFL
        results["models"]["kyle"] = {"error": "Kyle model is NBA-only"}
        
        # 3. Apex model
        try:
            from scripts.apex_model import predict_nfl_apex
            apex_result = await predict_nfl_apex(home_team, away_team, total_line, home_ml, away_ml)
            results["models"]["apex"] = apex_result
        except Exception as e:
            results["models"]["apex"] = {"error": str(e)}
        
        # Defensive cache storage
        try:
            await cache.store_games("nfl", [{"id": game_id, "home_team": home_team, "away_team": away_team, "analysis": results}])
        except Exception as ce:
            logger.warning(f"NFL Cache storage failed: {ce}")

        return results
    except Exception as e:
        logger.error(f"NFL model comparison error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/apex/backtest")
async def apex_backtest(
    sport: str = Query("nfl", description="Sport to backtest: nba or nfl"),
    test_year: int = Query(2024, description="Year to test on"),
    sample_size: int = Query(50, description="Max games to test (1-100)")
):
    """
    Run backtest on historical games to verify model accuracy.
    
    Returns concrete accuracy proof by testing on games where outcome is known.
    """
    try:
        from scripts.apex_trainer import backtest_on_historical
        
        # Limit sample size
        sample_size = min(max(1, sample_size), 100)
        
        return await backtest_on_historical(sport, test_year, sample_size)
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/ncaab/import')
async def import_ncaab_root(background_tasks: BackgroundTasks, start_year: int = Query(2018), end_year: int = Query(2025)):
    """Backend compatibility mirrored endpoint for NCAAB import."""
    import_status["ncaab"] = {
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "progress": [f"Import started for {start_year}-{end_year}"],
        "result": None,
        "error": None
    }
    background_tasks.add_task(run_ncaab_import, start_year, end_year)
    return {'status': 'started', 'message': f'Started NCAAB import {start_year}-{end_year}'}


@app.on_event("startup")
async def startup_event():
    """Initialize scheduler and import logs on startup."""
    try:
        await SchedulerService.init_db()
        SchedulerService.start_scheduler()
    except Exception as e:
        logger.error(f"Startup error: {e}")


# Standings endpoints to fix 404 errors for mobile app
@app.get("/standings/nfl")
async def get_nfl_standings_redirect(season: Optional[int] = None):
    """NFL standings endpoint - redirects to db endpoint."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    # Import here to avoid circular imports
    from api.db_endpoints import get_league_standings
    return await get_league_standings("nfl", season)


@app.get("/standings/nba") 
async def get_nba_standings_redirect(season: Optional[int] = None):
    """NBA standings endpoint - redirects to db endpoint."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    from api.db_endpoints import get_league_standings
    return await get_league_standings("nba", season)


@app.get("/standings/nascar")
async def get_nascar_standings_redirect(season: Optional[int] = None, series: str = "cup"):
    """NASCAR standings endpoint - redirects to db endpoint."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    from api.db_endpoints import get_nascar_standings
    return await get_nascar_standings(season, series)


@app.get("/nascar/results")
async def get_nascar_results_alt(season: Optional[int] = None, series: str = "cup"):
    """NASCAR results endpoint - mobile app compatibility."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    from api.db_endpoints import get_race_results_list
    return await get_race_results_list("nascar", series, season)


# ============================================
# Startup Event - Register Current Version
# ============================================
@app.on_event("startup")
async def startup_event():
    """Register current version on startup"""
    try:
        import asyncio
        from api.deployment_endpoints import register_current_version
        
        # Wait a moment for database to be ready
        await asyncio.sleep(2)
        
        result = await register_current_version()
        if result.get("success"):
            logger.info(f"Version registered: {result.get('deployment_id')}")
        else:
            logger.warning(f"Failed to register version: {result.get('error')}")
    except Exception as e:
        logger.warning(f"Could not register version on startup: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# Comprehensive NASCAR endpoints to handle any mobile app URL pattern
@app.get("/db/standings/nascar")
async def get_nascar_standings_db_alias(season: Optional[int] = None, series: str = "cup"):
    """NASCAR standings endpoint - database alias for mobile app compatibility."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    from api.db_endpoints import get_nascar_standings
    return await get_nascar_standings(season, series)


@app.get("/standings/nascar")
async def get_nascar_standings_redirect(season: Optional[int] = None, series: str = "cup"):
    """NASCAR standings endpoint - redirects to db endpoint."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    from api.db_endpoints import get_nascar_standings
    return await get_nascar_standings(season, series)


@app.get("/nascar/standings")
async def get_nascar_standings_alt(season: Optional[int] = None, series: str = "cup"):
    """NASCAR standings endpoint - mobile app compatibility."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    from api.db_endpoints import get_nascar_standings
    return await get_nascar_standings(season, series)


@app.get("/db/races/nascar/list")
async def get_nascar_results_db_alias(series: str = "cup", season: Optional[int] = None, driver: Optional[str] = None, limit: int = 200):
    """NASCAR results endpoint - database alias for mobile app compatibility."""
    from api.db_endpoints import get_race_results_list
    return await get_race_results_list("nascar", series, season, driver, limit)


@app.get("/nascar/results")
async def get_nascar_results_alt(season: Optional[int] = None, series: str = "cup"):
    """NASCAR results endpoint - mobile app compatibility."""
    from datetime import datetime
    if season is None:
        season = datetime.now().year
    
    from api.db_endpoints import get_race_results_list
    return await get_race_results_list("nascar", series, season)


# ============================================
# Startup Event - Register Current Version
# ============================================
@app.on_event("startup")
async def startup_event():
    """Register current version on startup"""
    try:
        import asyncio
        from api.deployment_endpoints import register_current_version
        
        # Wait a moment for database to be ready
        await asyncio.sleep(2)
        
        result = await register_current_version()
        if result.get("success"):
            logger.info(f"Version registered: {result.get('deployment_id')}")
        else:
            logger.warning(f"Failed to register version: {result.get('error')}")
    except Exception as e:
        logger.warning(f"Could not register version on startup: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

