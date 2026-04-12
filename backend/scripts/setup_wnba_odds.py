import os
from pathlib import Path
import pandas as pd

try:
    from kaggle.api.kaggle_api_extended import KaggleApi
except ImportError:
    print("ERROR: Kaggle API module not found. Run 'pip install kaggle'")
    exit(1)

def download_and_inspect_wnba_odds():
    try:
        api = KaggleApi()
        api.authenticate()
    except Exception as e:
        print(f"Kaggle Auth Failed: {e}")
        print("Ensure your kaggle.json exists in ~/.kaggle/kaggle.json")
        return

    # Create destination directory
    data_dir = Path(__file__).resolve().parents[1] / "data" / "wnba"
    data_dir.mkdir(parents=True, exist_ok=True)

    dataset = "zachht/wnba-odds-history"
    print(f"Downloading {dataset} to {data_dir}...")
    
    # Download and unzip
    api.dataset_download_files(dataset, path=str(data_dir), unzip=True)
    
    print("\nDownload complete. Files found:")
    csv_files = list(data_dir.glob("*.csv"))
    
    if not csv_files:
        print("WARNING: No CSV files found in the download!")
        return
        
    for f in csv_files:
        print(f" - {f.name} ({f.stat().st_size / 1024:.2f} KB)")
    
    # Inspect the first CSV to understand the schema for database import
    target_csv = csv_files[0]
    print(f"\n--- Schema Inspection of {target_csv.name} ---")
    try:
        df = pd.read_csv(target_csv, nrows=5)
        print("COLUMNS: ", df.columns.tolist())
        print("\nFIRST ROW:")
        print(df.iloc[0].to_dict())
    except Exception as e:
        print(f"Failed to read CSV: {e}")

if __name__ == "__main__":
    download_and_inspect_wnba_odds()
