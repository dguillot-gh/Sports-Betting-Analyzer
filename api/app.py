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
        try:
            if hasattr(model, 'predict_proba'):
                proba = model.predict_proba(X)[0, 1]
                resp['probability'] = float(proba)
        except Exception:
            pass
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
