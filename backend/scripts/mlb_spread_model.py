"""
MLB Spread Prediction Model
==============================
XGBoost classifier predicting P(home covers -1.5) for each MLB game.

Target: home_cover (1 = home team won by 2+, 0 = didn't)
Features: Same as moneyline model (~56 features)
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

from scripts.mlb_features import SPREAD_FEATURES

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "mlb"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "spread_xgb.joblib"


def train_spread_model(
    features_df: pd.DataFrame,
    feature_cols: List[str] = None,
    test_size: float = 0.2,
) -> Dict[str, Any]:
    """
    Train the spread (run line) prediction model.

    Target: home_cover = (home_runs - away_runs) >= 2
    """
    feature_cols = feature_cols or SPREAD_FEATURES

    df = features_df.sort_values("date").dropna(subset=["home_cover"])

    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = df[col].fillna(0.0)

    X = df[feature_cols].values.astype(np.float32)
    y = df["home_cover"].astype(int).values

    split_idx = int(len(df) * (1 - test_size))
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("xgb", XGBClassifier(
            n_estimators=250,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            reg_alpha=0.15,
            reg_lambda=1.2,
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

    test_df = df.iloc[split_idx:][
        ["date", "home_team", "away_team", "home_cover"]
    ].copy().reset_index(drop=True)
    test_df["pred_prob"] = y_prob
    test_df["pred_cover"] = y_pred
    test_df["correct"] = (test_df["pred_cover"] == test_df["home_cover"]).astype(int)

    joblib.dump(model, MODEL_PATH)
    logger.info(f"Spread model saved to {MODEL_PATH} | AUC={metrics['roc_auc']:.4f}")

    return {
        "model": model,
        "metrics": metrics,
        "importances": importances,
        "feature_cols": feature_cols,
        "test_df": test_df,
        "train_size": len(X_train),
        "test_size": len(X_test),
    }


def load_spread_model() -> Optional[Pipeline]:
    """Load the trained spread model from disk."""
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    return None


def predict_spread(model: Pipeline, features: Dict[str, Any], feature_cols: List[str] = None) -> Dict[str, Any]:
    """
    Predict P(home covers -1.5) for a single game.

    Returns:
        dict with home_cover_prob, pick, confidence
    """
    feature_cols = feature_cols or SPREAD_FEATURES
    X = np.array([[features.get(col, 0.0) for col in feature_cols]], dtype=np.float32)

    prob = model.predict_proba(X)[0][1]

    return {
        "home_cover_prob": round(float(prob), 4),
        "pick": "HOME -1.5" if prob > 0.5 else "AWAY +1.5",
        "confidence": round(float(max(prob, 1 - prob)), 4),
    }
