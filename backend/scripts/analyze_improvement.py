"""
NASCAR Model Improvement Analysis
Compare model performance with and without the scraped speed features
from ifantasyrace.com to validate their impact.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, classification_report
import warnings
warnings.filterwarnings('ignore')


def load_base_data():
    """Load the base NASCAR race data."""
    project_root = Path(__file__).parent.parent
    
    # Load NASCAR results from existing converted RDA files
    results_files = list((project_root / 'data' / 'nascar').rglob('race_results*.csv'))
    
    if not results_files:
        # Try to load from Cup folder
        results_files = list((project_root / 'data' / 'nascar' / 'raw' / 'cup').rglob('*.csv'))
    
    if not results_files:
        print("No NASCAR race results found. Using scraped data directly.")
        return None
    
    print(f"Found {len(results_files)} result files")
    dfs = [pd.read_csv(f) for f in results_files]
    return pd.concat(dfs, ignore_index=True)


def load_scraped_features():
    """Load the cleaned scraped speed features."""
    project_root = Path(__file__).parent.parent
    
    # Load cleaned speed rankings
    speed_file = project_root / 'data' / 'nascar' / 'cleaned' / 'speed_rankings_cleaned.csv'
    
    if not speed_file.exists():
        print(f"Speed rankings not found: {speed_file}")
        return None
    
    df = pd.read_csv(speed_file)
    print(f"Loaded {len(df)} scraped speed ranking records")
    return df


def load_driver_features():
    """Load aggregated driver speed features."""
    project_root = Path(__file__).parent.parent
    driver_file = project_root / 'data' / 'nascar' / 'integrated' / 'driver_speed_features.csv'
    
    if driver_file.exists():
        df = pd.read_csv(driver_file)
        print(f"Loaded driver features for {len(df)} drivers")
        return df
    return None


def load_track_features():
    """Load driver-track speed features."""
    project_root = Path(__file__).parent.parent
    track_file = project_root / 'data' / 'nascar' / 'integrated' / 'track_speed_features.csv'
    
    if track_file.exists():
        df = pd.read_csv(track_file)
        print(f"Loaded {len(df)} driver-track feature records")
        return df
    return None


def prepare_prediction_dataset(speed_df, driver_features, use_driver_features=True):
    """Prepare dataset for prediction from speed rankings data."""
    
    # Use the speed rankings data directly since we have finish positions
    df = speed_df.copy()
    
    # Create target: top 5 finish
    if 'finishing_position' in df.columns:
        df['finishing_position'] = pd.to_numeric(df['finishing_position'], errors='coerce')
        df = df.dropna(subset=['finishing_position'])
        df['top5_finish'] = (df['finishing_position'] <= 5).astype(int)
    else:
        print("No finishing_position column found")
        return None, None
    
    # Base features from raw data
    base_features = []
    
    if 'speed_rank' in df.columns:
        df['speed_rank'] = pd.to_numeric(df['speed_rank'], errors='coerce')
        base_features.append('speed_rank')
    
    if 'avg_speed_ranking' in df.columns:
        df['avg_speed_ranking'] = pd.to_numeric(df['avg_speed_ranking'], errors='coerce')
        base_features.append('avg_speed_ranking')
    
    # Add driver historical features if requested
    if use_driver_features and driver_features is not None:
        # Get first driver column (handle duplicates)
        driver_col = 'driver'
        if isinstance(df[driver_col], pd.DataFrame):
            df['driver_clean'] = df[driver_col].iloc[:, 0]
        else:
            df['driver_clean'] = df[driver_col]
        
        # Merge driver features
        driver_features_renamed = driver_features.rename(columns={
            'avg_speed_rank': 'driver_avg_speed',
            'avg_finish_position': 'driver_avg_finish',
            'races_tracked': 'driver_races'
        })
        
        df = df.merge(
            driver_features_renamed[['driver', 'driver_avg_speed', 'driver_avg_finish', 'driver_races']],
            left_on='driver_clean',
            right_on='driver',
            how='left',
            suffixes=('', '_hist')
        )
        
        # Add historical features
        for col in ['driver_avg_speed', 'driver_avg_finish', 'driver_races']:
            if col in df.columns:
                base_features.append(col)
    
    print(f"Features available: {base_features}")
    
    # Drop rows with missing features
    df = df.dropna(subset=base_features + ['top5_finish'])
    
    X = df[base_features]
    y = df['top5_finish']
    
    return X, y


def run_comparison():
    """Run the model comparison analysis."""
    print("=" * 60)
    print("NASCAR Model Improvement Analysis")
    print("Comparing performance with/without scraped speed features")
    print("=" * 60 + "\n")
    
    # Load data
    speed_df = load_scraped_features()
    driver_features = load_driver_features()
    
    if speed_df is None:
        print("ERROR: Could not load scraped data. Run the scraper first.")
        return
    
    # Prepare datasets
    print("\n--- Preparing Datasets ---")
    
    # Dataset WITHOUT driver historical features (just current race speed)
    X_base, y_base = prepare_prediction_dataset(speed_df, None, use_driver_features=False)
    
    # Dataset WITH driver historical features (includes scraped aggregations)
    X_enhanced, y_enhanced = prepare_prediction_dataset(speed_df, driver_features, use_driver_features=True)
    
    if X_base is None or X_enhanced is None:
        print("ERROR: Could not prepare datasets")
        return
    
    print(f"\nBase dataset: {len(X_base)} records, {len(X_base.columns)} features")
    print(f"Enhanced dataset: {len(X_enhanced)} records, {len(X_enhanced.columns)} features")
    
    # Split data
    X_train_base, X_test_base, y_train_base, y_test_base = train_test_split(
        X_base, y_base, test_size=0.2, random_state=42
    )
    
    X_train_enh, X_test_enh, y_train_enh, y_test_enh = train_test_split(
        X_enhanced, y_enhanced, test_size=0.2, random_state=42
    )
    
    # Train models
    print("\n--- Training Models ---")
    
    model_base = GradientBoostingClassifier(n_estimators=100, random_state=42)
    model_base.fit(X_train_base, y_train_base)
    
    model_enhanced = GradientBoostingClassifier(n_estimators=100, random_state=42)
    model_enhanced.fit(X_train_enh, y_train_enh)
    
    # Evaluate
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    # Base model
    y_pred_base = model_base.predict(X_test_base)
    acc_base = accuracy_score(y_test_base, y_pred_base)
    
    print(f"\n[BASE MODEL] (current race speed only)")
    print(f"   Features: {list(X_base.columns)}")
    print(f"   Accuracy: {acc_base:.1%}")
    
    # Enhanced model
    y_pred_enh = model_enhanced.predict(X_test_enh)
    acc_enhanced = accuracy_score(y_test_enh, y_pred_enh)
    
    print(f"\n[ENHANCED MODEL] (+ driver historical features)")
    print(f"   Features: {list(X_enhanced.columns)}")
    print(f"   Accuracy: {acc_enhanced:.1%}")
    
    # Improvement
    improvement = acc_enhanced - acc_base
    print(f"\n>>> IMPROVEMENT: {improvement:+.1%}")
    
    if improvement > 0:
        print(f"   [YES] The scraped data IMPROVES model accuracy by {improvement:.1%} points!")
    elif improvement == 0:
        print(f"   [--] No significant change in accuracy")
    else:
        print(f"   [NO] Performance decreased (may need more data or tuning)")
    
    # Feature importance
    print(f"\n[Feature Importance] (Enhanced Model):")
    importances = pd.DataFrame({
        'feature': X_enhanced.columns,
        'importance': model_enhanced.feature_importances_
    }).sort_values('importance', ascending=False)
    
    for _, row in importances.iterrows():
        print(f"   {row['feature']}: {row['importance']:.3f}")
    
    print("\n" + "=" * 60)
    
    return {
        'base_accuracy': acc_base,
        'enhanced_accuracy': acc_enhanced,
        'improvement': improvement,
        'feature_importance': importances.to_dict()
    }


if __name__ == '__main__':
    run_comparison()
