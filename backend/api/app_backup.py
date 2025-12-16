# api/app.py
from pathlib import Path
import sys
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import joblib
import yaml

# Make repo modules importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from sports.nascar import NASCARSport  # noqa: E402
from sports.nfl import NFLSport        # noqa: E402
from data_loader import load_sport_data  # noqa: E402
import train as train_mod               # noqa: E402

app = FastAPI(title='Sports ML API', version='1.0')

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

# ---------- Helpers ----------

def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f'Config not found: {path}')
    return yaml.safe_load(open(path, 'r', encoding='utf-8'))


def get_nfl() -> NFLSport:
    cfg = load_yaml(CFG_DIR / 'nfl_config.yaml')
    return NFLSport(cfg)

# Map a series keyword to a NASCAR config override
SERIES_TO_RDA = {
    'cup': 'cup_series.rda',
    'xfinity': 'xfinity_series.rda',
    'truck': 'truck_series.rda',
}


def build_nascar(series: Optional[str]) -> tuple[NASCARSport, str]:
    """Create a NASCARSport with config adjusted for the requested series.
    Returns (sport_instance, series_label) where series_label is used for model dirs.
    """
    cfg = load_yaml(CFG_DIR / 'nascar_config.yaml')

    label = 'csv'  # default label if you keep CSV as configured
    if series:
        s = series.lower().strip()
        if s == 'all':
            # Force the loader to scan all RDA files by clearing data block
            cfg['data'] = {}
            label = 'all'
        elif s in SERIES_TO_RDA:
            # Point directly to a specific RDA file
            cfg.setdefault('data', {})
            cfg['data']['results_file'] = SERIES_TO_RDA[s]
            label = s
        elif s == 'csv':
            # Keep whatever CSV is in your YAML (defaults to nascar race data.csv)
            label = 'csv'
        else:
            raise HTTPException(status_code=400, detail=f"Unknown series '{series}'. Use cup|xfinity|truck|all|csv.")

    return NASCARSport(cfg), label


# Cache helpers (optional; simple on-demand load is fine too)
from threading import Lock
MODEL_CACHE: dict[tuple[str, str, str], object] = {}
CACHE_LOCK = Lock()


def model_paths(sport: str, series_label: str, task: str) -> Path:
    # E.g., models/nascar/cup/classification_model.joblib
    return MODELS_DIR / sport / series_label / f'{task}_model.joblib'


# ---------- Health ----------
@app.get('/health')
def health():
    return {'ok': True, 'sports': ['nascar', 'nfl']}


# ---------- NASCAR ----------
@app.get('/nascar/schema')
def nascar_schema(series: Optional[str] = None):
    sport, _ = build_nascar(series)
    return {
        'features': sport.get_feature_columns(),
        'targets': sport.get_target_columns(),
        'series': series or 'csv'
    }


@app.get('/nascar/data')
def nascar_data(series: Optional[str] = None, limit: int = 1000,
                year_min: Optional[int] = None, year_max: Optional[int] = None,
                track_type: Optional[str] = None):
    sport, _ = build_nascar(series)
    df = load_sport_data(sport)
    if 'year' in df.columns:
        if year_min is not None:
            df = df[df['year'] >= year_min]
        if year_max is not None:
            df = df[df['year'] <= year_max]
    if track_type and 'track_type' in df.columns:
        df = df[df['track_type'] == track_type]
    out = df.head(limit)
    return {
        'columns': out.columns.tolist(),
        'rows': out.to_dict(orient='records'),
        'total_rows': int(len(df))
    }


@app.post('/nascar/train/{task}')
def nascar_train(task: str, series: Optional[str] = None, test_start: Optional[int] = None):
    if task not in ('classification', 'regression'):
        raise HTTPException(status_code=400, detail='task must be classification or regression')

    sport, label = build_nascar(series)
    out_dir = MODELS_DIR / 'nascar' / label

    model_path, metrics_path, metrics = train_mod.train_and_evaluate_sport(
        sport=sport,
        task=task,
        out_dir=out_dir,
        test_start_season=test_start,
    )

    # Cache model in memory
    with CACHE_LOCK:
        MODEL_CACHE[('nascar', label, task)] = joblib.load(model_path)

    return {
        'series': label,
        'model_path': str(model_path),
        'metrics_path': str(metrics_path),
        'metrics': metrics,
    }


@app.post('/nascar/predict/{task}')
def nascar_predict(task: str, payload: dict, series: Optional[str] = None):
    if task not in ('classification', 'regression'):
        raise HTTPException(status_code=400, detail='task must be classification or regression')

    sport, label = build_nascar(series)
    key = ('nascar', label, task)

    model = MODEL_CACHE.get(key)
    if model is None:
        path = model_paths('nascar', label, task)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"No trained {task} model for NASCAR series '{label}'. Train first.")
        model = joblib.load(path)

    feats = sport.get_feature_columns()
    cols = feats.get('categorical', []) + feats.get('boolean', []) + feats.get('numeric', [])

    row = {c: payload.get(c, None) for c in cols}
    X = pd.DataFrame([row], columns=cols)

    pred = model.predict(X)[0]
    resp = {'series': label, 'prediction': float(pred) if task == 'regression' else int(pred)}
    try:
        proba = model.predict_proba(X)[0, 1]
        resp['probability'] = float(proba)
    except Exception:
        pass
    return resp


# ---------- NFL (no series) ----------
@app.get('/nfl/schema')
def nfl_schema():
    s = get_nfl()
    return {'features': s.get_feature_columns(), 'targets': s.get_target_columns()}


@app.get('/nfl/data')
def nfl_data(limit: int = 1000, season_min: Optional[int] = None, season_max: Optional[int] = None):
    s = get_nfl()
    df = load_sport_data(s)
    if 'schedule_season' in df.columns:
        if season_min is not None:
            df = df[df['schedule_season'] >= season_min]
        if season_max is not None:
            df = df[df['schedule_season'] <= season_max]
    out = df.head(limit)
    return {'columns': out.columns.tolist(), 'rows': out.to_dict(orient='records'), 'total_rows': int(len(df))}


@app.post('/nfl/train/{task}')
def nfl_train(task: str, test_start: Optional[int] = None):
    if task not in ('classification', 'regression'):
        raise HTTPException(status_code=400, detail='task must be classification or regression')

    s = get_nfl()
    out_dir = MODELS_DIR / 'nfl'
    model_path, metrics_path, metrics = train_mod.train_and_evaluate_sport(
        sport=s, task=task, out_dir=out_dir, test_start_season=test_start)
    return {'model_path': str(model_path), 'metrics_path': str(metrics_path), 'metrics': metrics}


@app.post('/nfl/predict/{task}')
def nfl_predict(task: str, payload: dict):
    if task not in ('classification', 'regression'):
        raise HTTPException(status_code=400, detail='task must be classification or regression')

    path = MODELS_DIR / 'nfl' / f'{task}_model.joblib'
    if not path.exists():
        raise HTTPException(status_code=404, detail=f'No trained {task} model for NFL. Train first.')
    model = joblib.load(path)

    s = get_nfl()
    feats = s.get_feature_columns()
    cols = feats.get('categorical', []) + feats.get('boolean', []) + feats.get('numeric', [])
    row = {c: payload.get(c, None) for c in cols}
    X = pd.DataFrame([row], columns=cols)

    pred = model.predict(X)[0]
    resp = {'prediction': float(pred) if task == 'regression' else int(pred)}
    try:
        proba = model.predict_proba(X)[0, 1]
        resp['probability'] = float(proba)
    except Exception:
        pass
    return resp
