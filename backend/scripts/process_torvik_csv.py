"""
Process Torvik Raw CSV
Reads backend/data/ncaab/raw_torvik.csv and generates Parquet files.
"""
import pandas as pd
from pathlib import Path
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("process_torvik")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "ncaab"
CSV_PATH = DATA_DIR / "raw_torvik.csv"

def process_csv():
    logger.info(f"Processing CSV from {CSV_PATH}")
    if not CSV_PATH.exists():
        logger.error("Raw CSV not found!")
        return

    try:
        # Load CSV without header, Torvik raw often has no header or variable
        # Based on subagent output: "UC Santa Barbara",115.76...
        # It seems to be headerless or the header was stripped.
        # Let's assume standard Torvik columns based on inspection:
        # Team, AdjOE, AdjDE, Barthag, Record, Conf, ...
        # Let's inspect the first line
        
        df = pd.read_csv(CSV_PATH, header=None)
        
        # Manually assign columns based on known Torvik format (partial)
        # 0: Team ("UC Santa Barbara")
        # 1: AdjOE (115.76)
        # 2: AdjDE (115.605)
        # 3: Barthag (0.503848)
        # 4: Record ("11-7")
        # ...
        # 15: Tempo? (64.2358) -> Let's check visual data
        # 2026 -> Season
        
        # Based on visual mapping:
        # Col 0: Team
        # Col 1: AdjOE
        # Col 2: AdjDE
        # Col 3: Barthag
        # Col 15: Adj Tempo (approx 60-75)
        # Col 21: EFG Off?
        # Col 22: EFG Def?
        
        # Let's define a basic mapping for now
        df = df.rename(columns={
            0: 'team',
            1: 'adj_o',
            2: 'adj_d',
            3: 'barthag',
            15: 'adj_t'
        })
        
        # Ensure numeric
        for col in ['adj_o', 'adj_d', 'barthag', 'adj_t']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        df['fetch_date'] = datetime.now().strftime('%Y-%m-%d')
        df['conf'] = "N/A" # Not critical for now

        # Save Ratings
        ratings_df = df[['team', 'conf', 'barthag', 'adj_o', 'adj_d', 'adj_t', 'fetch_date']].copy()
        output_path = DATA_DIR / "torvik_ratings.parquet"
        ratings_df.to_parquet(output_path, index=False)
        logger.info(f"Saved {len(ratings_df)} Torvik ratings to {output_path}")
        
        # Determine stats columns (Four Factors)
        # This is harder without headers. I'll skip stats for now and focus on Ratings which are key for O/U (Tempo).
        # We can try to guess headers later if needed.
        
    except Exception as e:
        logger.error(f"Processing failed: {e}")

if __name__ == "__main__":
    process_csv()
