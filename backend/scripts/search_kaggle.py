import os
from kaggle.api.kaggle_api_extended import KaggleApi

def search_odds():
    api = KaggleApi()
    api.authenticate()
    
    # Search for NBA odds
    nba_datasets = api.dataset_list(search="nba odds")
    print("--- NBA Odds Datasets ---")
    for d in nba_datasets:
        print(f"{d.ref} | {d.lastUpdated} | {d.size}")

if __name__ == "__main__":
    search_odds()
