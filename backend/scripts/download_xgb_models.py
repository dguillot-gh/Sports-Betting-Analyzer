#!/usr/bin/env python3
"""
Dynamic XGBoost Model Downloader for kyleskom's NBA-Machine-Learning-Sports-Betting repo.
Scans the GitHub repository and downloads the best available ML and O/U models.
"""

import os
import re
import json
import urllib.request
import urllib.error
from pathlib import Path

# Configuration
GITHUB_REPO = "kyleskom/NBA-Machine-Learning-Sports-Betting"
MODELS_PATH = "Models/XGBoost_Models"
LOCAL_DIR = Path("scripts/nba_ml_reference/Models/XGBoost_Models")

# GitHub API endpoint for listing directory contents
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MODELS_PATH}"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/master/{MODELS_PATH}"


def get_model_list():
    """Fetch list of model files from GitHub API."""
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "Python"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            return [f["name"] for f in data if f["name"].endswith(".json")]
    except Exception as e:
        print(f"Error fetching model list: {e}")
        return []


def parse_model_info(filename):
    """
    Parse model filename to extract type and accuracy.
    Examples:
        XGBoost_68.9%_ML-3.json -> ('ML', 68.9, 3)
        XGBoost_54.8%_UO-8.json -> ('OU', 54.8, 8)
    """
    match = re.match(r'XGBoost_(\d+\.?\d*)%_(ML|UO)-(\d+)\.json', filename)
    if match:
        accuracy = float(match.group(1))
        model_type = "ML" if match.group(2) == "ML" else "OU"
        version = int(match.group(3))
        return model_type, accuracy, version
    return None, 0, 0


def find_best_models(model_files):
    """Find the best ML and O/U models by accuracy."""
    ml_models = []
    ou_models = []
    
    for filename in model_files:
        model_type, accuracy, version = parse_model_info(filename)
        if model_type == "ML":
            ml_models.append((accuracy, version, filename))
        elif model_type == "OU":
            ou_models.append((accuracy, version, filename))
    
    # Sort by accuracy (descending), then version (descending)
    ml_models.sort(key=lambda x: (x[0], x[1]), reverse=True)
    ou_models.sort(key=lambda x: (x[0], x[1]), reverse=True)
    
    best_ml = ml_models[:2] if ml_models else []  # Get top 2 ML models
    best_ou = ou_models[:2] if ou_models else []  # Get top 2 O/U models
    
    return best_ml, best_ou


def download_model(filename, local_dir):
    """Download a model file from GitHub."""
    url = f"{GITHUB_RAW_URL}/{urllib.parse.quote(filename)}"
    local_path = local_dir / filename
    
    try:
        print(f"  Downloading: {filename}")
        req = urllib.request.Request(url, headers={"User-Agent": "Python"})
        with urllib.request.urlopen(req, timeout=60) as response:
            with open(local_path, 'wb') as f:
                f.write(response.read())
        print(f"  ✓ Saved to: {local_path}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to download {filename}: {e}")
        return False


def main():
    print("=" * 60)
    print("NBA XGBoost Model Downloader")
    print(f"Repository: {GITHUB_REPO}")
    print("=" * 60)
    
    # Create local directory
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    
    # Fetch available models
    print("\n[1/3] Fetching available models from GitHub...")
    model_files = get_model_list()
    
    if not model_files:
        print("ERROR: Could not fetch model list. Check network connection.")
        return 1
    
    print(f"Found {len(model_files)} model files:")
    for f in model_files:
        print(f"  - {f}")
    
    # Find best models
    print("\n[2/3] Identifying best models...")
    best_ml, best_ou = find_best_models(model_files)
    
    if not best_ml:
        print("ERROR: No ML models found!")
        return 1
    
    print(f"Best ML models:")
    for acc, ver, name in best_ml:
        print(f"  - {name} (accuracy: {acc}%)")
    
    print(f"Best O/U models:")
    for acc, ver, name in best_ou:
        print(f"  - {name} (accuracy: {acc}%)")
    
    # Download models
    print("\n[3/3] Downloading models...")
    downloaded = 0
    
    for acc, ver, filename in best_ml:
        if download_model(filename, LOCAL_DIR):
            downloaded += 1
    
    for acc, ver, filename in best_ou:
        if download_model(filename, LOCAL_DIR):
            downloaded += 1
    
    total_to_download = len(best_ml) + len(best_ou)
    print(f"\n✓ Downloaded {downloaded}/{total_to_download} models successfully")
    
    # Write metadata file for reference
    metadata = {
        "source_repo": GITHUB_REPO,
        "ml_models": [{"filename": f, "accuracy": a} for a, v, f in best_ml],
        "ou_models": [{"filename": f, "accuracy": a} for a, v, f in best_ou],
        "downloaded_at": __import__("datetime").datetime.now().isoformat()
    }
    
    with open(LOCAL_DIR / "model_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Saved metadata to {LOCAL_DIR / 'model_metadata.json'}")
    
    return 0 if downloaded == total_to_download else 1


if __name__ == "__main__":
    import urllib.parse
    exit(main())
