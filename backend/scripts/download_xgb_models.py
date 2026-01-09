#!/usr/bin/env python3
"""
Dynamic Model Downloader (XGBoost + Neural Network)
for kyleskom's NBA-Machine-Learning-Sports-Betting repo.

Scans the GitHub repository and downloads:
1. Best XGBoost Models (.json) + Calibration (.pkl)
2. Best Neural Network Models (.h5/.keras) + Calibration (.pkl)
3. Essential Data files (Schedule)
"""

import os
import re
import json
import urllib.request
import urllib.error
from pathlib import Path

# Configuration
GITHUB_REPO = "kyleskom/NBA-Machine-Learning-Sports-Betting"
MODELS_PATH_XGB = "Models/XGBoost_Models"
MODELS_PATH_NN = "Models/NN_Models"
DATA_PATH = "Data"

LOCAL_MODELS_XGB_DIR = Path("scripts/nba_ml_reference/Models/XGBoost_Models")
LOCAL_MODELS_NN_DIR = Path("scripts/nba_ml_reference/Models/NN_Models")
LOCAL_DATA_DIR = Path("scripts/nba_ml_reference/Data")

# GitHub API endpoints
GITHUB_API_MODELS_XGB = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MODELS_PATH_XGB}"
GITHUB_API_MODELS_NN = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MODELS_PATH_NN}"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/master"

# Regex patterns (from XGBoost_Runner.py and NN_Runner.py)
XGB_ACCURACY_PATTERN = re.compile(r"XGBoost_(\d+(?:\.\d+)?)%_")
NN_ML_PATTERN = re.compile(r"Trained-Model-ML-(\d+(?:\.\d+)?)")
NN_OU_PATTERN = re.compile(r"Trained-Model-OU-(\d+(?:\.\d+)?)")


def get_file_list(api_url):
    """Fetch list of all files in a directory via GitHub API."""
    try:
        req = urllib.request.Request(
            api_url,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "Python"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            return [f["name"] for f in data]
    except Exception as e:
        print(f"Error fetching file list from {api_url}: {e}")
        return []


def download_file(path_suffix, local_dir):
    """Download a single file."""
    url = f"{GITHUB_RAW_URL}/{urllib.parse.quote(path_suffix)}"
    local_path = local_dir / Path(path_suffix).name
    
    try:
        print(f"  Downloading: {Path(path_suffix).name}")
        req = urllib.request.Request(url, headers={"User-Agent": "Python"})
        with urllib.request.urlopen(req, timeout=120) as response: # Increased timeout for large NN files
            with open(local_path, 'wb') as f:
                f.write(response.read())
        print(f"  [OK] Saved to: {local_path}")
        return True
    except Exception as e:
        print(f"  [FAIL] Failed to download {path_suffix}: {e}")
        return False


def main():
    print("=" * 60)
    print("NBA Model Downloader (XGBoost + Neural Network)")
    print(f"Repository: {GITHUB_REPO}")
    print("=" * 60)
    
    LOCAL_MODELS_XGB_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_MODELS_NN_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # ---------------------------------------------------------
    # 1. Download Data (Schedule)
    # ---------------------------------------------------------
    print("\n[1/4] Syncing Schedule Data...")
    sch_files = ["nba-2025-UTC.csv"]
    data_downloaded = 0
    for f in sch_files:
        if download_file(f"{DATA_PATH}/{f}", LOCAL_DATA_DIR):
            data_downloaded += 1
            
    # ---------------------------------------------------------
    # 2. Fetch XGBoost Models
    # ---------------------------------------------------------
    print("\n[2/4] Fetching XGBoost Model List...")
    xgb_files = get_file_list(GITHUB_API_MODELS_XGB)
    
    # Filter for .json models and .pkl calibration files
    xgb_targets = [f for f in xgb_files if XGB_ACCURACY_PATTERN.search(f) and (f.endswith('.json') or f.endswith('.pkl'))]
    
    if not xgb_targets:
        print("WARNING: No XGBoost models found!")
    
    print(f"\n[3/4] Downloading {len(xgb_targets)} XGBoost files...")
    xgb_downloaded = 0
    for f in xgb_targets:
        if download_file(f"{MODELS_PATH_XGB}/{f}", LOCAL_MODELS_XGB_DIR):
            xgb_downloaded += 1

    # ---------------------------------------------------------
    # 3. Fetch Neural Network Models
    # ---------------------------------------------------------
    print("\n[4/4] Fetching Neural Network Model List...")
    nn_files = get_file_list(GITHUB_API_MODELS_NN)
    
    # Filter for .h5/.keras models and .pkl calibration files matching patterns
    # NN_Runner.py looks for "Trained-Model-ML-..." and "Trained-Model-OU-..."
    nn_targets = []
    for f in nn_files:
        is_ml = NN_ML_PATTERN.search(f)
        is_ou = NN_OU_PATTERN.search(f)
        is_model_ext = f.endswith('.h5') or f.endswith('.keras')
        is_cal_ext = f.endswith('.pkl')
        
        if (is_ml or is_ou) and (is_model_ext or is_cal_ext):
            nn_targets.append(f)

    if not nn_targets:
        print("WARNING: No Neural Network models found!")
    else:
        print(f"Found {len(nn_targets)} Neural Network files.")
        
        # Download NN models
        nn_downloaded = 0
        for f in nn_targets:
            if download_file(f"{MODELS_PATH_NN}/{f}", LOCAL_MODELS_NN_DIR):
                nn_downloaded += 1
            
    print(f"\nSync Complete.")
    print(f"  Data Files: {data_downloaded}/{len(sch_files)}")
    print(f"  XGBoost Models: {xgb_downloaded}/{len(xgb_targets)}")
    print(f"  NN Models: {nn_downloaded if 'nn_downloaded' in locals() else 0}/{len(nn_targets)}")
    
    return 0

if __name__ == "__main__":
    exit(main())
