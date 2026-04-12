"""
MLB Totals Prediction Model
==============================
LightGBM + XGBoost ensemble predicting P(game goes over) for each MLB game.

Target: went_over (1 = total runs > posted O/U, 0 = under)
Features: ~60 features (all base features + LOB + exp_total)
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
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

try:
    from lightgbm import LGBMClassifier
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

from scripts.mlb_features import TOTALS_FEATURES

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "mlb"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PATH = MODEL_DIR / "totals_ensemble.joblib"


def train_totals_model(
    features_df: pd.DataFrame,
    feature_cols: List[str] = None,
    test_size: float = 0.2,
) -> Dict[str, Any]:
    """
    Train the over/under totals prediction model.

    Uses a LightGBM + XGBoost ensemble (0.5/0.5 blend) when LightGBM is
    available, otherwise falls back to XGBoost only.

    Target: went_over = (total_runs > over_under)
    """
    feature_cols = feature_cols or TOTALS_FEATURES

    df = features_df.sort_values("date").dropna(subset=["went_over"])

    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = df[col].fillna(0.0)

    X = df[feature_cols].values.astype(np.float32)
    y = df["went_over"].astype(int).values

    split_idx = int(len(df) * (1 - test_size))
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    # --- XGBoost ---
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    xgb_model = XGBClassifier(
        n_estimators=250,
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
    )
    xgb_model.fit(X_train_scaled, y_train)
    xgb_prob = xgb_model.predict_proba(X_test_scaled)[:, 1]

    # --- LightGBM (if available) ---
    lgb_model = None
    lgb_prob = None
    if HAS_LIGHTGBM:
        lgb_model = LGBMClassifier(
            n_estimators=250,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        lgb_model.fit(X_train_scaled, y_train)
        lgb_prob = lgb_model.predict_proba(X_test_scaled)[:, 1]

    # --- Ensemble blend ---
    if lgb_prob is not None:
        y_prob = 0.5 * xgb_prob + 0.5 * lgb_prob
    else:
        y_prob = xgb_prob

    y_pred = (y_prob >= 0.5).astype(int)

    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "brier_score": float(brier_score_loss(y_test, y_prob)),
        "log_loss": float(log_loss(y_test, y_prob)),
        "roc_auc": float(roc_auc_score(y_test, y_prob)),
        "has_lightgbm": HAS_LIGHTGBM,
    }

    importances = pd.DataFrame({
        "feature": feature_cols,
        "importance": xgb_model.feature_importances_,
    }).sort_values("importance", ascending=False).reset_index(drop=True)

    test_df = df.iloc[split_idx:][
        ["date", "home_team", "away_team", "went_over"]
    ].copy().reset_index(drop=True)
    test_df["pred_prob"] = y_prob
    test_df["pred_over"] = y_pred
    test_df["correct"] = (test_df["pred_over"] == test_df["went_over"]).astype(int)

    # Save ensemble as a dict
    ensemble = {
        "scaler": scaler,
        "xgb": xgb_model,
        "lgb": lgb_model,
        "feature_cols": feature_cols,
        "has_lightgbm": HAS_LIGHTGBM,
    }
    joblib.dump(ensemble, MODEL_PATH)
    logger.info(f"Totals ensemble saved to {MODEL_PATH} | AUC={metrics['roc_auc']:.4f}")

    return {
        "model": ensemble,
        "metrics": metrics,
        "importances": importances,
        "feature_cols": feature_cols,
        "test_df": test_df,
        "train_size": len(X_train),
        "test_size": len(X_test),
    }


def load_totals_model() -> Optional[Dict]:
    """Load the trained totals ensemble from disk."""
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    return None


def predict_totals(ensemble: Dict, features: Dict[str, Any], feature_cols: List[str] = None) -> Dict[str, Any]:
    """
    Predict P(over) for a single game.

    Returns:
        dict with over_prob, pick (OVER/UNDER), confidence
    """
    feature_cols = feature_cols or ensemble.get("feature_cols", TOTALS_FEATURES)
    scaler = ensemble["scaler"]
    xgb = ensemble["xgb"]
    lgb = ensemble.get("lgb")

    X = np.array([[features.get(col, 0.0) for col in feature_cols]], dtype=np.float32)
    X_scaled = scaler.transform(X)

    xgb_prob = xgb.predict_proba(X_scaled)[0][1]

    if lgb is not None:
        lgb_prob = lgb.predict_proba(X_scaled)[0][1]
        prob = 0.5 * xgb_prob + 0.5 * lgb_prob
    else:
        prob = xgb_prob

    return {
        "over_prob": round(float(prob), 4),
        "pick": "OVER" if prob > 0.5 else "UNDER",
        "confidence": round(float(max(prob, 1 - prob)), 4),
    }
