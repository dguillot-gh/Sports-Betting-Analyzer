"""
NASCAR Data Integration Module
Integrates cleaned scraped data with existing NASCAR datasets.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NASCARDataIntegrator:
    """Integrates scraped data with existing NASCAR race data."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.cleaned_dir = self.project_root / 'data' / 'nascar' / 'cleaned'
        self.raw_dir = self.project_root / 'data' / 'nascar' / 'raw'
        self.output_dir = self.project_root / 'data' / 'nascar' / 'integrated'
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def load_existing_data(self) -> pd.DataFrame:
        """Load existing NASCAR race results from RDA converted data."""
        # Try loading the existing results
        results_file = self.raw_dir / 'race_results.csv'
        if not results_file.exists():
            # Try from Cup subdirectory
            results_file = self.raw_dir / 'cup' / 'race_results.csv'
        
        if results_file.exists():
            logger.info(f"Loading existing data from {results_file}")
            df = pd.read_csv(results_file)
            logger.info(f"Loaded {len(df)} existing records")
            return df
        
        logger.warning("No existing race results found")
        return pd.DataFrame()
    
    def load_scraped_speed_rankings(self) -> pd.DataFrame:
        """Load cleaned speed rankings data."""
        speed_file = self.cleaned_dir / 'speed_rankings_cleaned.csv'
        
        if not speed_file.exists():
            logger.warning(f"Cleaned speed rankings not found: {speed_file}")
            return pd.DataFrame()
        
        df = pd.read_csv(speed_file)
        logger.info(f"Loaded {len(df)} speed ranking records")
        return df
    
    def create_driver_speed_features(self, speed_df: pd.DataFrame) -> pd.DataFrame:
        """Create driver-level speed features from scraped data."""
        if speed_df.empty:
            return pd.DataFrame()
        
        logger.info("Creating driver speed features...")
        
        # Aggregate speed rankings by driver
        driver_features = speed_df.groupby('driver').agg({
            'speed_rank': 'mean',
            'avg_speed_ranking': 'mean',
            'finishing_position': ['mean', 'min', 'count']
        }).round(2)
        
        # Flatten column names
        driver_features.columns = [
            'avg_speed_rank',
            'avg_overall_speed_rank', 
            'avg_finish_position',
            'best_finish',
            'races_tracked'
        ]
        
        driver_features = driver_features.reset_index()
        
        logger.info(f"Created features for {len(driver_features)} drivers")
        return driver_features
    
    def create_track_speed_features(self, speed_df: pd.DataFrame) -> pd.DataFrame:
        """Create driver-by-track speed features."""
        if speed_df.empty:
            return pd.DataFrame()
        
        logger.info("Creating driver-by-track speed features...")
        
        # Aggregate by driver AND track
        track_features = speed_df.groupby(['driver', 'track']).agg({
            'speed_rank': 'mean',
            'avg_speed_ranking': 'mean',
            'finishing_position': ['mean', 'count']
        }).round(2)
        
        track_features.columns = [
            'track_avg_speed_rank',
            'track_overall_speed_rank',
            'track_avg_finish',
            'track_races'
        ]
        
        track_features = track_features.reset_index()
        
        logger.info(f"Created {len(track_features)} driver-track feature records")
        return track_features
    
    def integrate_with_existing(self, existing_df: pd.DataFrame, 
                                 driver_features: pd.DataFrame,
                                 track_features: pd.DataFrame) -> pd.DataFrame:
        """Merge scraped features with existing race data."""
        if existing_df.empty:
            logger.warning("No existing data to integrate with")
            return pd.DataFrame()
        
        logger.info("Integrating scraped features with existing data...")
        
        # Find the driver column in existing data
        driver_col = None
        for col in ['driver', 'Driver', 'driver_name', 'full_name']:
            if col in existing_df.columns:
                driver_col = col
                break
        
        if driver_col is None:
            logger.error("Could not find driver column in existing data")
            return existing_df
        
        # Standardize driver column name for merge
        existing_df = existing_df.rename(columns={driver_col: 'driver_name'})
        
        # Merge driver features
        if not driver_features.empty:
            merged = existing_df.merge(
                driver_features.rename(columns={'driver': 'driver_name'}),
                on='driver_name',
                how='left',
                suffixes=('', '_scraped')
            )
            logger.info(f"Merged driver features: {len(merged)} records")
        else:
            merged = existing_df
        
        # Find track column
        track_col = None
        for col in ['track', 'Track', 'track_name', 'circuit']:
            if col in merged.columns:
                track_col = col
                break
        
        # Merge track features if we have track column
        if track_col and not track_features.empty:
            merged = merged.rename(columns={track_col: 'track_name'})
            merged = merged.merge(
                track_features.rename(columns={
                    'driver': 'driver_name',
                    'track': 'track_name'
                }),
                on=['driver_name', 'track_name'],
                how='left',
                suffixes=('', '_track')
            )
            logger.info(f"Merged track features: {len(merged)} records")
        
        return merged
    
    def run_integration(self) -> pd.DataFrame:
        """Run the full integration pipeline."""
        logger.info("=" * 60)
        logger.info("Starting NASCAR data integration")
        logger.info("=" * 60)
        
        # Load data
        speed_df = self.load_scraped_speed_rankings()
        
        if speed_df.empty:
            logger.error("No scraped data to integrate")
            return pd.DataFrame()
        
        # Create features from scraped data
        driver_features = self.create_driver_speed_features(speed_df)
        track_features = self.create_track_speed_features(speed_df)
        
        # Save standalone feature files
        if not driver_features.empty:
            driver_file = self.output_dir / 'driver_speed_features.csv'
            driver_features.to_csv(driver_file, index=False)
            logger.info(f"Saved driver features to {driver_file}")
        
        if not track_features.empty:
            track_file = self.output_dir / 'track_speed_features.csv'
            track_features.to_csv(track_file, index=False)
            logger.info(f"Saved track features to {track_file}")
        
        # Try to integrate with existing data
        existing_df = self.load_existing_data()
        
        if not existing_df.empty:
            integrated = self.integrate_with_existing(
                existing_df, driver_features, track_features
            )
            
            if not integrated.empty:
                output_file = self.output_dir / 'nascar_integrated.csv'
                integrated.to_csv(output_file, index=False)
                logger.info(f"Saved integrated data to {output_file}")
                
                self._print_summary(integrated, driver_features, track_features)
                return integrated
        
        logger.info("=" * 60)
        logger.info("Integration complete (standalone features only)")
        logger.info("=" * 60)
        
        return driver_features
    
    def _print_summary(self, integrated: pd.DataFrame, 
                       driver_features: pd.DataFrame,
                       track_features: pd.DataFrame):
        """Print integration summary."""
        logger.info("\n" + "=" * 60)
        logger.info("INTEGRATION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Driver features: {len(driver_features)} drivers")
        logger.info(f"Track features: {len(track_features)} driver-track combos")
        logger.info(f"Integrated records: {len(integrated)}")
        logger.info(f"Final columns: {len(integrated.columns)}")
        
        # Check feature coverage
        new_cols = ['avg_speed_rank', 'track_avg_speed_rank']
        for col in new_cols:
            if col in integrated.columns:
                coverage = integrated[col].notna().sum() / len(integrated) * 100
                logger.info(f"  {col} coverage: {coverage:.1f}%")
        
        logger.info("=" * 60)


def main():
    integrator = NASCARDataIntegrator()
    integrator.run_integration()


if __name__ == '__main__':
    main()
