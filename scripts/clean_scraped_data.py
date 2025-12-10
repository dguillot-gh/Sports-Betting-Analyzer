"""
NASCAR Scraped Data Cleaner
Cleans and standardizes scraped data from ifantasyrace.com to match
the format of existing NASCAR datasets.
"""

import pandas as pd
import numpy as np
import re
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NASCARDataCleaner:
    """Cleans and standardizes scraped NASCAR data."""
    
    # Standard driver name mappings (scraped name -> canonical name)
    DRIVER_NAME_MAP = {
        'Martin Truex Jr': 'Martin Truex Jr.',
        'Martin Truex Jr.': 'Martin Truex Jr.',
        'Kyle Busch': 'Kyle Busch',
        'Denny Hamlin': 'Denny Hamlin',
        'Chase Elliott': 'Chase Elliott',
        'William Byron': 'William Byron',
        'Corey LaJoie': 'Corey LaJoie',
        'Erik Jones': 'Erik Jones',
        'Ross Chastain': 'Ross Chastain',
        # Add more as needed
    }
    
    # Track name standardization
    TRACK_NAME_MAP = {
        'atlanta': 'Atlanta Motor Speedway',
        'bristol': 'Bristol Motor Speedway', 
        'charlotte': 'Charlotte Motor Speedway',
        'chicago': 'Chicago Street Course',
        'cota': 'Circuit of the Americas',
        'darlington': 'Darlington Raceway',
        'daytona': 'Daytona International Speedway',
        'dover': 'Dover Motor Speedway',
        'gateway': 'Gateway Motorsports Park',
        'homestead': 'Homestead-Miami Speedway',
        'indianapolis': 'Indianapolis Motor Speedway',
        'iowa': 'Iowa Speedway',
        'kansas': 'Kansas Speedway',
        'las vegas': 'Las Vegas Motor Speedway',
        'martinsville': 'Martinsville Speedway',
        'michigan': 'Michigan International Speedway',
        'nashville': 'Nashville Superspeedway',
        'new hampshire': 'New Hampshire Motor Speedway',
        'phoenix': 'Phoenix Raceway',
        'pocono': 'Pocono Raceway',
        'richmond': 'Richmond Raceway',
        'sonoma': 'Sonoma Raceway',
        'talladega': 'Talladega Superspeedway',
        'texas': 'Texas Motor Speedway',
        'watkins glen': 'Watkins Glen International',
        'roval': 'Charlotte Motor Speedway Road Course',
        'echopark': 'Atlanta Motor Speedway',  # EchoPark is at Atlanta
    }
    
    def __init__(self, scraped_dir: str = None, output_dir: str = None):
        if scraped_dir is None:
            scraped_dir = Path(__file__).parent.parent / 'data' / 'nascar' / 'scraped'
        self.scraped_dir = Path(scraped_dir)
        
        if output_dir is None:
            output_dir = Path(__file__).parent.parent / 'data' / 'nascar' / 'cleaned'
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def clean_driver_name(self, name: str) -> str:
        """Standardize driver name."""
        if pd.isna(name):
            return None
        
        name = str(name).strip()
        
        # Check mapping
        if name in self.DRIVER_NAME_MAP:
            return self.DRIVER_NAME_MAP[name]
        
        return name
    
    def extract_track_from_url(self, url: str) -> str:
        """Extract standardized track name from URL."""
        if pd.isna(url):
            return 'Unknown'
        
        url = str(url).lower()
        
        # Extract track slug from URL
        for key, value in self.TRACK_NAME_MAP.items():
            if key in url:
                return value
        
        # Try to extract from URL pattern
        match = re.search(r'/\d{4}/\d{2}/\d{2}/([\w-]+)', url)
        if match:
            slug = match.group(1).replace('-', ' ').title()
            return slug
        
        return 'Unknown'
    
    def extract_race_date_from_url(self, url: str) -> str:
        """Extract race date from URL."""
        if pd.isna(url):
            return None
        
        match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', str(url))
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        return None
    
    def clean_numeric_column(self, series: pd.Series) -> pd.Series:
        """Clean numeric column - handle NaN, convert to float."""
        return pd.to_numeric(series, errors='coerce')
    
    def clean_speed_rankings(self) -> pd.DataFrame:
        """Clean and standardize speed rankings data."""
        input_file = self.scraped_dir / 'speed_rankings.csv'
        
        if not input_file.exists():
            logger.warning(f"Speed rankings file not found: {input_file}")
            return pd.DataFrame()
        
        logger.info(f"Cleaning speed rankings from {input_file}")
        df = pd.read_csv(input_file)
        
        original_count = len(df)
        logger.info(f"Loaded {original_count} records")
        
        # Extract track and date from URLs
        df['track'] = df['source_url'].apply(self.extract_track_from_url)
        df['race_date'] = df['source_url'].apply(self.extract_race_date_from_url)
        
        # Clean driver names
        if 'Driver' in df.columns:
            df['driver'] = df['Driver'].apply(self.clean_driver_name)
        
        # Standardize column names (lowercase, underscores)
        df.columns = [
            re.sub(r'[^\w]', '_', c.lower().strip())
            .replace('__', '_')
            .strip('_')
            for c in df.columns
        ]
        
        # Identify and clean numeric columns
        numeric_patterns = ['rank', 'speed', 'finish', 'lap', 'avg']
        for col in df.columns:
            if any(p in col for p in numeric_patterns):
                if isinstance(df[col], pd.Series):
                    df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Extract year/season from race_date
        df['season'] = pd.to_datetime(df['race_date'], errors='coerce').dt.year
        
        # Create standardized columns for integration
        df_clean = df.rename(columns={
            'rank': 'speed_rank',
            'finish': 'finishing_position',
            'avg_speed_rank': 'avg_speed_ranking'
        })
        
        # Keep only relevant columns
        keep_cols = [
            'driver', 'track', 'race_date', 'season',
            'speed_rank', 'finishing_position', 'avg_speed_ranking'
        ]
        # Add any segment speed columns
        for col in df_clean.columns:
            if 'lap' in col and col not in keep_cols:
                keep_cols.append(col)
        
        # Filter to columns that exist
        keep_cols = [c for c in keep_cols if c in df_clean.columns]
        df_clean = df_clean[keep_cols]
        
        # Remove rows with no driver name
        df_clean = df_clean.dropna(subset=['driver'])
        
        # Remove duplicates
        df_clean = df_clean.drop_duplicates()
        
        logger.info(f"Cleaned: {original_count} -> {len(df_clean)} records")
        
        # Save cleaned data
        output_file = self.output_dir / 'speed_rankings_cleaned.csv'
        df_clean.to_csv(output_file, index=False)
        logger.info(f"Saved cleaned data to {output_file}")
        
        # Generate summary
        self._log_data_summary(df_clean, "Speed Rankings")
        
        return df_clean
    
    def clean_loop_data(self) -> pd.DataFrame:
        """Clean and standardize loop data."""
        input_file = self.scraped_dir / 'loop_data.csv'
        
        if not input_file.exists():
            logger.warning(f"Loop data file not found: {input_file}")
            return pd.DataFrame()
        
        logger.info(f"Cleaning loop data from {input_file}")
        df = pd.read_csv(input_file)
        
        original_count = len(df)
        
        # Extract track and date from URLs
        df['track'] = df['source_url'].apply(self.extract_track_from_url)
        df['race_date'] = df['source_url'].apply(self.extract_race_date_from_url)
        
        # Standardize column names
        df.columns = [
            re.sub(r'[^\w]', '_', c.lower().strip())
            .replace('__', '_')
            .strip('_')
            for c in df.columns
        ]
        
        # Clean numeric columns
        for col in df.columns.unique():
            try:
                if col in df.columns and isinstance(df[col], pd.Series) and df[col].dtype == object:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            except Exception:
                pass  # Skip problematic columns
        
        # Remove duplicates and empty rows
        df = df.dropna(how='all')
        df = df.drop_duplicates()
        
        logger.info(f"Cleaned: {original_count} -> {len(df)} records")
        
        # Save
        output_file = self.output_dir / 'loop_data_cleaned.csv'
        df.to_csv(output_file, index=False)
        logger.info(f"Saved cleaned data to {output_file}")
        
        return df
    
    def _log_data_summary(self, df: pd.DataFrame, name: str):
        """Log a summary of the cleaned data."""
        logger.info(f"\n{'='*50}")
        logger.info(f"{name} Summary:")
        logger.info(f"  Total records: {len(df)}")
        
        # Get unique column names (remove duplicates)
        unique_cols = list(dict.fromkeys(df.columns))
        logger.info(f"  Columns ({len(unique_cols)}): {unique_cols[:10]}...")
        
        if 'driver' in df.columns:
            if isinstance(df['driver'], pd.Series):
                logger.info(f"  Unique drivers: {df['driver'].nunique()}")
        if 'track' in df.columns:
            if isinstance(df['track'], pd.Series):
                logger.info(f"  Unique tracks: {df['track'].nunique()}")
        if 'season' in df.columns:
            if isinstance(df['season'], pd.Series):
                seasons = sorted([int(s) for s in df['season'].dropna().unique()])
                logger.info(f"  Seasons: {seasons}")
        
        logger.info(f"{'='*50}\n")
    
    def clean_all(self):
        """Clean all scraped data files."""
        logger.info("Starting data cleaning process...")
        
        results = {}
        
        # Clean speed rankings
        speed_df = self.clean_speed_rankings()
        results['speed_rankings'] = len(speed_df)
        
        # Clean loop data
        loop_df = self.clean_loop_data()
        results['loop_data'] = len(loop_df)
        
        logger.info("\nCleaning complete!")
        logger.info(f"Output directory: {self.output_dir}")
        
        return results


def main():
    cleaner = NASCARDataCleaner()
    cleaner.clean_all()


if __name__ == '__main__':
    main()
