"""
MLB Moneyline Prediction Model
================================
XGBoost classifier predicting P(home_win) for each MLB game.

Target: home_win (1 = home team won, 0 = away team won)
Features: ~56 team + pitcher + context + matchup features
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from scripts.mlb_features import MONEYLINE_FEATURES

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "mlb"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "moneyline_xgb.joblib"


def train_moneyline_model(
    features_df: pd.DataFrame,
    feature_cols: List[str] = None,
    test_size: float = 0.2,
) -> Dict[str, Any]:
    """
    Train the home-win moneyline prediction model.

    Uses chronological train/test split to prevent look-ahead bias.

    Args:
        features_df: DataFrame with feature columns + 'home_win' target + 'date' column.
        feature_cols: Feature columns to use (default: MONEYLINE_FEATURES).
        test_size: Fraction of most-recent games for testing.

    Returns:
        dict with: model, metrics, importances, feature_cols, test_df
    """
    feature_cols = feature_cols or MONEYLINE_FEATURES

    df = features_df.sort_values("date").dropna(subset=["home_win"])

    # Fill NaN features with 0 for training
    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = df[col].fillna(0.0)

    X = df[feature_cols].values.astype(np.float32)
    y = df["home_win"].astype(int).values

    split_idx = int(len(df) * (1 - test_size))
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", XGBClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            reg_alpha=0.1,
            reg_lambda=1.0,
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )),
    ])
    model.fit(X_train, y_train)

    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "brier_score": float(brier_score_loss(y_test, y_prob)),
        "log_loss": float(log_loss(y_test, y_prob)),
        "roc_auc": float(roc_auc_score(y_test, y_prob)),
    }

    importances = pd.DataFrame({
        "feature": feature_cols,
        "importance": model.named_steps["xgb"].feature_importances_,
    }).sort_values("importance", ascending=False).reset_index(drop=True)

    # Test set with predictions for backtest
    test_df = df.iloc[split_idx:][
        ["date", "home_team", "away_team", "home_win"]
    ].copy().reset_index(drop=True)
    test_df["pred_prob"] = y_prob
    test_df["pred_win"] = y_pred
    test_df["correct"] = (test_df["pred_win"] == test_df["home_win"]).astype(int)

    joblib.dump(model, MODEL_PATH)
    logger.info(f"Moneyline model saved to {MODEL_PATH} | AUC={metrics['roc_auc']:.4f}")

    return {
        "model": model,
        "metrics": metrics,
        "importances": importances,
        "feature_cols": feature_cols,
        "test_df": test_df,
        "train_size": len(X_train),
        "test_size": len(X_test),
    }


def load_moneyline_model() -> Optional[Pipeline]:
    """Load the trained moneyline model from disk."""
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    return None


def predict_moneyline(model: Pipeline, features: Dict[str, Any], feature_cols: List[str] = None) -> Dict[str, Any]:
    """
    Predict P(home_win) for a single game using its feature dict.

    Returns:
        dict with home_win_prob, predicted_winner_is_home, confidence
    """
    feature_cols = feature_cols or MONEYLINE_FEATURES
    X = np.array([[features.get(col, 0.0) for col in feature_cols]], dtype=np.float32)

    prob = model.predict_proba(X)[0][1]

    return {
        "home_win_prob": round(float(prob), 4),
        "predicted_winner_is_home": prob > 0.5,
        "confidence": round(float(max(prob, 1 - prob)), 4),
    }
