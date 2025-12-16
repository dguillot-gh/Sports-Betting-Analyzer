"""
Prediction utilities for trained models.
"""
from pathlib import Path
from typing import Dict, Any, Optional, Union
import pandas as pd
import joblib


def load_model(sport: str, task: str, model_dir: Optional[Path] = None) -> Any:
    """
    Load a trained model for a sport and task.

    Args:
        sport: Sport name (e.g., 'nfl', 'nba')
        task: Task type ('classification' or 'regression')
        model_dir: Directory containing models (defaults to models/{sport})

    Returns:
        Loaded sklearn pipeline
    """
    if model_dir is None:
        model_dir = Path('models') / sport

    model_path = model_dir / f"{task}_model.joblib"
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    return joblib.load(model_path)


def predict_games(pipeline: Any, games_df: pd.DataFrame,
                  return_probabilities: bool = True) -> Dict[str, Any]:
    """
    Make predictions on new games data.

    Args:
        pipeline: Trained sklearn pipeline
        games_df: DataFrame with game features
        return_probabilities: Whether to return probabilities for classification

    Returns:
        Dictionary with predictions and optional probabilities
    """
    predictions = pipeline.predict(games_df)

    result = {'predictions': predictions.tolist()}

    # Try to get probabilities for classification models
    if return_probabilities:
        try:
            probabilities = pipeline.predict_proba(games_df)
            # For binary classification, return probability of positive class
            if probabilities.shape[1] == 2:
                result['probabilities'] = probabilities[:, 1].tolist()
            else:
                result['probabilities'] = probabilities.tolist()
        except Exception:
            # Some models don't support predict_proba
            pass

    return result


def predict_single_game(pipeline: Any, game_features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Make prediction for a single game.

    Args:
        pipeline: Trained sklearn pipeline
        game_features: Dictionary of game features

    Returns:
        Dictionary with prediction and optional probability
    """
    game_df = pd.DataFrame([game_features])
    return predict_games(pipeline, game_df, return_probabilities=True)
