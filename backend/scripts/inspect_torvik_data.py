
import pandas as pd
from pathlib import Path

def inspect_data():
    base_dir = Path("c:/Users/dguil/source/repos/PythonMLService/backend/data/ncaab")
    path = base_dir / "torvik_ratings.parquet"
    
    if not path.exists():
        print(f"File not found: {path}")
        return

    df = pd.read_parquet(path)
    print("\n--- Torvik Ratings Dtypes ---")
    print(df.dtypes)
    print("\n--- First 5 Rows ---")
    print(df.head())
    
    print("\n--- Inspecting specific values (adj_o) ---")
    print(df['adj_o'].head(10).apply(type))
    print(df['adj_o'].head(10).values)

if __name__ == "__main__":
    inspect_data()
