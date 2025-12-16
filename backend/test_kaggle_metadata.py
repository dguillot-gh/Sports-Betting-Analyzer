
import os
import json
from pathlib import Path
from kaggle.api.kaggle_api_extended import KaggleApi

# Setup credentials manually for test
os.environ['KAGGLE_USERNAME'] = 'danman2901'
os.environ['KAGGLE_KEY'] = 'KGAT_e42c6b3e06534822adac671631ede3f7'

def test_metadata():
    try:
        api = KaggleApi()
        api.authenticate()
        
        dataset = "sumitrodatta/nba-aba-baa-stats"
        print(f"Fetching metadata for {dataset}...")
        
        # list_datasets returns a list of Dataset objects
        datasets = api.dataset_list(user="sumitrodatta", search="nba-aba-baa-stats")
        
        for d in datasets:
            # Check if this is the exact match
            if d.ref == dataset:
                print(f"Match found: {d.ref}")
                print(f"Attributes: {dir(d)}")
                return
        
        print("Dataset not found in search results.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_metadata()
