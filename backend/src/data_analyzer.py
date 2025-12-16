"""
Data Analyzer Module
Analyzes data quality, feature impact, and provides improvement recommendations.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


class DataAnalyzer:
    """Analyzes dataset quality and provides recommendations."""
    
    # Ideal features for each sport (what would improve predictions)
    IDEAL_FEATURES = {
        'nfl': [
            'weather_temperature', 'weather_wind', 'weather_precipitation',
            'home_injuries_count', 'away_injuries_count',
            'home_days_rest', 'away_days_rest',
            'home_travel_distance', 'away_travel_distance',
            'primetime_game', 'divisional_game',
            'home_qb_rating', 'away_qb_rating'
        ],
        'nba': [
            'home_days_rest', 'away_days_rest',
            'home_back_to_back', 'away_back_to_back',
            'home_injuries_count', 'away_injuries_count',
            'altitude_difference',
            'home_travel_distance', 'away_travel_distance'
        ],
        'nascar': [
            'weather_temperature', 'weather_humidity',
            'tire_compound', 'fuel_strategy',
            'practice_speed', 'qualifying_position',
            'recent_crashes', 'pit_crew_rating'
        ]
    }
    
    # Estimated improvement per feature category
    FEATURE_IMPACT_ESTIMATES = {
        'weather': 3.0,  # ~3% accuracy improvement
        'injuries': 4.0,
        'rest_days': 2.5,
        'travel': 1.5,
        'matchup_history': 2.0,
        'momentum': 2.0,
        'player_props': 3.5
    }
    
    @staticmethod
    def analyze_feature_correlations(df: pd.DataFrame, features: list, threshold: float = 0.8) -> dict:
        """Find highly correlated features that might be redundant."""
        # Get numeric columns only
        numeric_cols = [f for f in features if f in df.columns and pd.api.types.is_numeric_dtype(df[f])]
        
        if len(numeric_cols) < 2:
            return {'high_correlations': [], 'recommendation': None}
        
        # Calculate correlation matrix
        corr_matrix = df[numeric_cols].corr()
        
        # Find high correlations
        high_corr = []
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                if abs(corr_matrix.iloc[i, j]) >= threshold:
                    high_corr.append({
                        'feature1': corr_matrix.columns[i],
                        'feature2': corr_matrix.columns[j],
                        'correlation': round(corr_matrix.iloc[i, j], 3)
                    })
        
        recommendation = None
        if high_corr:
            recommendation = f"Found {len(high_corr)} highly correlated feature pairs. Consider removing redundant features to reduce overfitting."
        
        return {
            'high_correlations': high_corr[:10],  # Limit to top 10
            'recommendation': recommendation
        }
    
    @staticmethod
    def analyze_missing_features(sport: str, existing_features: list) -> list:
        """Identify missing features that could improve predictions."""
        ideal = DataAnalyzer.IDEAL_FEATURES.get(sport.lower(), [])
        existing_lower = [f.lower() for f in existing_features]
        
        missing = []
        for feature in ideal:
            # Check if feature or similar exists
            feature_found = any(feature.replace('_', '') in f.replace('_', '') or 
                               f.replace('_', '') in feature.replace('_', '') 
                               for f in existing_lower)
            if not feature_found:
                # Estimate impact category
                impact_cat = 'weather' if 'weather' in feature else \
                            'injuries' if 'injur' in feature else \
                            'rest_days' if 'rest' in feature or 'back_to_back' in feature else \
                            'travel' if 'travel' in feature else 'other'
                
                estimated_impact = DataAnalyzer.FEATURE_IMPACT_ESTIMATES.get(impact_cat, 1.0)
                
                missing.append({
                    'feature': feature,
                    'category': impact_cat,
                    'estimated_impact': f"~{estimated_impact}% accuracy improvement",
                    'difficulty': 'Medium' if 'weather' in feature else 'Hard'
                })
        
        return sorted(missing, key=lambda x: float(x['estimated_impact'].replace('~', '').replace('%', '').split()[0]), reverse=True)
    
    @staticmethod
    def generate_recommendations(quality_data: dict, sport: str) -> list:
        """Generate prioritized improvement recommendations."""
        recommendations = []
        priority = 1
        
        # Check sample size
        total_rows = quality_data.get('summary', {}).get('total_rows', 0)
        if total_rows < 1000:
            recommendations.append({
                'priority': priority,
                'category': 'Data Volume',
                'issue': f'Only {total_rows} rows of data',
                'suggestion': 'Add more historical seasons to improve model generalization',
                'estimated_impact': 'High',
                'difficulty': 'Easy'
            })
            priority += 1
        elif total_rows < 5000:
            recommendations.append({
                'priority': priority,
                'category': 'Data Volume',
                'issue': f'Moderate dataset size ({total_rows} rows)',
                'suggestion': 'Consider adding 2-3 more seasons of historical data',
                'estimated_impact': 'Medium',
                'difficulty': 'Easy'
            })
            priority += 1
        
        # Check class balance
        class_balance = quality_data.get('class_balance', {})
        if class_balance and not isinstance(list(class_balance.values())[0], dict):
            minority_pct = min(class_balance.values()) if class_balance else 50
            if minority_pct < 10:
                recommendations.append({
                    'priority': priority,
                    'category': 'Class Balance',
                    'issue': f'Severe imbalance: minority class is only {minority_pct}%',
                    'suggestion': 'Use class_weight="balanced" or try SMOTE oversampling',
                    'estimated_impact': 'High',
                    'difficulty': 'Easy'
                })
                priority += 1
        
        # Check missing values
        missing = quality_data.get('missing_values', {})
        high_missing = [k for k, v in missing.items() if v > 50]
        if high_missing:
            recommendations.append({
                'priority': priority,
                'category': 'Data Quality',
                'issue': f'{len(high_missing)} features have >50% missing values',
                'suggestion': f'Consider dropping or imputing: {", ".join(high_missing[:3])}...',
                'estimated_impact': 'Medium',
                'difficulty': 'Easy'
            })
            priority += 1
        
        # Check for missing ideal features
        existing_features = list(quality_data.get('feature_coverage', {}).keys())
        missing_features = DataAnalyzer.analyze_missing_features(sport, existing_features)
        
        for mf in missing_features[:3]:  # Top 3 missing features
            recommendations.append({
                'priority': priority,
                'category': 'Missing Features',
                'issue': f'Missing: {mf["feature"].replace("_", " ").title()}',
                'suggestion': f'Adding this could improve accuracy by {mf["estimated_impact"]}',
                'estimated_impact': mf['estimated_impact'],
                'difficulty': mf['difficulty']
            })
            priority += 1
        
        # Suggest rolling features if not present
        rolling_features = [f for f in existing_features if 'rolling' in f.lower()]
        if not rolling_features:
            recommendations.append({
                'priority': priority,
                'category': 'Feature Engineering',
                'issue': 'No rolling average features detected',
                'suggestion': 'Add 5-game rolling averages for key stats (PPG, yards, etc.)',
                'estimated_impact': '~3-5% accuracy improvement',
                'difficulty': 'Medium'
            })
            priority += 1
        
        return recommendations[:8]  # Limit to top 8
    
    @staticmethod
    def get_feature_impact_from_model(sport: str, series: str = None) -> list:
        """Get feature importance from the most recent trained model."""
        try:
            models_dir = Path(__file__).parent.parent / 'models' / sport
            if series:
                models_dir = models_dir / series
            
            # Find most recent metrics file
            metrics_files = list(models_dir.glob('**/metrics.json'))
            if not metrics_files:
                return []
            
            # Use most recently modified
            latest = max(metrics_files, key=lambda p: p.stat().st_mtime)
            
            with open(latest, 'r') as f:
                metrics = json.load(f)
            
            feature_importance = metrics.get('feature_importance', [])
            
            # Format for display
            if isinstance(feature_importance, list):
                return [{'feature': fi['feature'], 'importance': round(fi['importance'], 4)} 
                        for fi in feature_importance[:15]]
            
            return []
        except Exception as e:
            logger.error(f"Error loading feature importance: {e}")
            return []
