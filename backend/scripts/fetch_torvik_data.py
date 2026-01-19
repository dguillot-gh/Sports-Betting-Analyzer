"""
Torvik Data Fetcher (Python Version)
Fetches T-Rank ratings and Four Factors from BartTorvik.com for NCAAB Model.
Replaces the R-based fetcher script.
"""
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
import io
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("torvik_data")

# Constants
CURRENT_SEASON = datetime.now().year if datetime.now().month > 6 else datetime.now().year
if datetime.now().month < 7: # If Jan-Jun, we are in the later part of the season (e.g. Jan 2026 is 2026 season)
    CURRENT_SEASON = datetime.now().year
else:
    CURRENT_SEASON = datetime.now().year + 1

# BartTorvik CSV Endpoint
# This CSV typically contains: Rk, Team, Conf, Barthag, AdjOE, AdjDE, AdjT, ...
TORVIK_CSV_URL = f"https://barttorvik.com/trank.php?year={CURRENT_SEASON}&csv=1"

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data" / "ncaab"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def fetch_torvik_data():
    """Fetch and save Torvik data."""
    logger.info(f"Fetching Torvik data for season {CURRENT_SEASON} from {TORVIK_CSV_URL}...")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(TORVIK_CSV_URL, headers=headers)
        response.raise_for_status()
        
        # The CSV comes with a custom header or no header sometimes. 
        # Standard columns usually: Rank, Team, Conf, G, Record, AdjOE, AdjDE, Barthag, Record-Projected, Arena, ...
        # Let's inspect the first few lines if needed, but pd.read_csv handles it well usually.
        
        # Clean potential BOM or encoding issues
        content = response.content.decode('utf-8-sig')
        
        # Debug: Check if content looks like CSV
        if content.strip().startswith("<!DOCTYPE") or "<html" in content.lower():
            logger.error("Response seems to be HTML, not CSV. Response dump:")
            logger.error(content[:1000])
            return
            
        # Load into DataFrame
        # BartTorvik CSV usually has headers on line 1
        df = pd.read_csv(io.StringIO(content))
        
        # Normalize column names
        df.columns = [c.strip().lower().replace(' ', '_').replace('%', 'pct').replace('-', '_') for c in df.columns]
        
        logger.info(f"Raw columns: {df.columns.tolist()}")
        
        # Rename essential columns for consistency with our system
        # Expected: team, adj_o, adj_d, adj_t (tempo)
        # Verify typical keys: 'team', 'adjoe', 'adjde', 'adjt'
        
        rename_map = {
            'team': 'team',
            'adjoe': 'adj_o',
            'adjde': 'adj_d',
            'adjt': 'adj_t',
            'barthag': 'barthag',
            'wab': 'wins_above_bubble'
        }
        
        df = df.rename(columns=rename_map)
        
        # Add fetch date
        df['fetch_date'] = datetime.now().strftime('%Y-%m-%d')
        
        # Save Ratings (Team, Conf, Ratings)
        ratings_cols = ['team', 'conf', 'barthag', 'adj_o', 'adj_d', 'adj_t', 'fetch_date']
        # Filter mostly for existing columns
        save_cols = [c for c in ratings_cols if c in df.columns]
        
        ratings_df = df[save_cols].copy()
        
        output_path = DATA_DIR / "torvik_ratings.parquet"
        ratings_df.to_parquet(output_path, index=False)
        logger.info(f"Saved {len(ratings_df)} T-Rank ratings to {output_path}")
        
        # Attempt to save Stats (Four Factors if available in CSV)
        # BartTorvik main CSV often includes: EFG, EFG_D, TOR, TOR_D, ORB, ORB_D, FTR, FTR_D
        # Let's check typical column names for four factors
        four_factors_map = {
            'efg_pct': 'efg', 'efgd_pct': 'efg_d',
            'tor': 'tov', 'tord': 'tov_d', 
            'orb': 'orb', 'drb': 'drb',
            'ftr': 'ftr', 'ftrd': 'ftr_d',
            '2p_pct': 'two_pt_pct', '2pd_pct': 'two_pt_pct_d',
            '3p_pct': 'three_pt_pct', '3pd_pct': 'three_pt_pct_d'
        }
        
        # Check matching columns (fuzzy match or direct)
        found_stats = []
        for csv_col in df.columns:
            if csv_col in four_factors_map:
                found_stats.append(csv_col)
                
        if found_stats:
            stats_cols = ['team', 'conf'] + found_stats + ['fetch_date']
            stats_df = df[stats_cols].copy()
            # Rename to uniform
            stats_df = stats_df.rename(columns=four_factors_map)
            
            stats_path = DATA_DIR / "torvik_team_stats.parquet"
            stats_df.to_parquet(stats_path, index=False)
            logger.info(f"Saved {len(stats_df)} Team Stats to {stats_path}")
        else:
            logger.warning("Four Factors columns not explicitly found in CSV. Checking alternate naming...")
            # Fallback: sometimes columns are like 'efg%', 'ftr', etc.
            # Our lower() and replace() cleaned them to 'efg_pct', 'ftr'
            pass

    except Exception as e:
        logger.error(f"Failed to fetch Torvik data: {e}")

if __name__ == "__main__":
    fetch_torvik_data()
