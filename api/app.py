# api/app.py
from pathlib import Path
import sys
import json
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import joblib
import yaml
import logging

# Make repo modules importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from data_loader import load_sport_data
import train as train_mod
import nascar_enhancer
from sport_factory import SportFactory
from simulation import SimulationEngine
from dataset_manager import DatasetManager

# Use the new MultiDatasetUpdater and others
from data_sources import NASCARDataUpdater, NFLDataUpdater, GitHubDataSource, MultiDatasetUpdater, BaseDataUpdater

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title='Sports ML API', version='1.2')

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
    return {'ok': True, 'sports': ['nascar', 'nfl', 'nba'], 'version': '1.2'}


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
            model = joblib.load(model_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'Failed to load model: {e}')

        # Read CSV
        try:
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
        "nfl": {"source": "Kaggle", "files": [], "datasets": []},
        "nba": {"source": "Kaggle", "files": [], "datasets": []}
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
    """Get metadata for a specific dataset including Kaggle last update date."""
    metadata = DATASET_MANAGER.get_kaggle_metadata(dataset_id)
    update_check = DATASET_MANAGER.check_for_updates(sport, dataset_id)
    
    return {
        "dataset_id": dataset_id,
        "metadata": metadata,
        "update_status": update_check
    }


class AddDatasetRequest(BaseModel):
    dataset_id: str
    type: str = "kaggle"

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
    datasets = DATASET_MANAGER.get_datasets(sport)
    if not datasets:
        return {}
        
    updater = MultiDatasetUpdater(REPO_ROOT / 'data' / sport, datasets)
    updates = updater.check_updates()
    return updates

@app.get('/data/history/{sport}')
def get_history(sport: str):
    data_dir = REPO_ROOT / 'data' / sport
    updater = BaseDataUpdater(data_dir) # Use base to just read history
    return updater.get_history()

# Unified update endpoint
@app.post('/data/update/{sport}')
def update_data(sport: str, dataset: Optional[str] = None):
    # Special handling for NASCAR (GitHub) vs others (Kaggle)
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
    
    if not datasets and sport in ['nfl', 'nba']:
        # Fallback for "legacy" or "default" if datasets.json is empty?
        # Maybe auto-add default if missing?
        # For NFL: tobycrabtree/nfl-scores-and-betting-data
        # For NBA: sumitrodatta/nba-aba-baa-stats
        # Let's add them transparently if config is empty for smooth transition
        default = None
        if sport == 'nfl': default = "tobycrabtree/nfl-scores-and-betting-data"
        if sport == 'nba': default = "sumitrodatta/nba-aba-baa-stats"
        
        if default:
            DATASET_MANAGER.add_dataset(sport, default)
            datasets = DATASET_MANAGER.get_datasets(sport)

    if not datasets:
         raise HTTPException(status_code=400, detail="No datasets configured for this sport. Please add one.")

    updater = MultiDatasetUpdater(data_dir, datasets)
    result = updater.update(specific_dataset_id=dataset)
    
    # Update timestamps in manager
    if result["success"]:
        for ds_id in result["updated"]:
            DATASET_MANAGER.update_timestamp(sport, ds_id)
            
    return result


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
