import sys
import os
from pathlib import Path
import traceback

# Add backend to sys.path
current_dir = Path(__file__).parent
sys.path.append(str(current_dir))

print(f"Attempting to import scripts.nfl_season_simulator from {current_dir}")

try:
    from scripts import nfl_season_simulator
    print("Import successful!")
except Exception:
    traceback.print_exc()
