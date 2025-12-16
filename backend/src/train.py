"""
Unified training module for all sports.
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd
import joblib

from sports.base import BaseSport
from data_loader import load_sport_data, chronological_split
from model_pipeline import build_pipeline, evaluate_model, sanitize_metrics


def train_and_evaluate_sport(
    sport: BaseSport,
    task: str,
    out_dir: Path,
    test_start_season: Optional[int] = None,
    train_start_season: Optional[int] = None,
    hyperparameters: Optional[Dict[str, Any]] = None
) -> tuple:
    """
    Train and evaluate a model for a given sport.

    Args:
        sport: Sport implementation instance
        task: 'classification' or 'regression'
        out_dir: Directory to save model and metrics
        test_start_season: Season year for test split
        train_start_season: Season year to start training data from
        hyperparameters: Optional dict of model hyperparameters

    Returns:
        Tuple of (model_path, metrics_path, metrics_dict)
    """
    # Load and prepare data
    df = load_sport_data(sport)

    # Get sport-specific configuration
    feature_cols = sport.get_feature_columns()
    target_cols = sport.get_target_columns()

    if task not in target_cols:
        raise ValueError(f"Task '{task}' not supported for sport '{sport.name}'")

    target_col = target_cols[task]

    # Drop rows without target
    score_cols = ['score_home', 'score_away']  # Generic score columns
    df = df.dropna(subset=[col for col in score_cols if col in df.columns] or [target_col])

    # Filter by train_start_season if provided
    time_col = 'schedule_season'  # Default, can be overridden per sport
    if train_start_season:
        if time_col in df.columns:
            df = df[df[time_col] >= train_start_season]
        elif 'year' in df.columns:
             df = df[df['year'] >= train_start_season]

    # Build pipeline
    pipeline = build_pipeline(feature_cols, task, hyperparameters)

    # Train/test split
    train_df, test_df, split_season = chronological_split(df, test_start_season, time_col)

    # Flatten feature columns for training
    all_features = []
    for col_list in feature_cols.values():
        all_features.extend(col_list)

    X_train = train_df[all_features]
    y_train = train_df[target_col]
    X_test = test_df[all_features]
    y_test = test_df[target_col]

    # Fit pipeline
    pipeline.fit(X_train, y_train)

    # Evaluate
    metrics = evaluate_model(pipeline, X_test, y_test, task)
    metrics['test_start_season'] = int(split_season)
    
    # Save hyperparameters used
    if hyperparameters:
        metrics['hyperparameters'] = hyperparameters

    # Final sanitization of all metrics including those added above
    metrics = sanitize_metrics(metrics)

    # Save model and metrics
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"{task}_model.joblib"
    joblib.dump(pipeline, model_path)

    metrics_path = out_dir / f"{task}_metrics.json"
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2)

    return model_path, metrics_path, metrics
