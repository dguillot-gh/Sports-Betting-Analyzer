import asyncio, sys, os, json
from pathlib import Path
sys.path.insert(0, str(Path(os.getcwd()) / 'backend'))

from scripts.college_baseball_predictor import CollegeBaseballPredictor
import scripts.college_baseball_predictor as mod

async def main():
    predictor = CollegeBaseballPredictor()
    stats_dir = mod._find_data_dir()
    print(f"Stats dir: {stats_dir}")
    print(f"XGB stat loaded: {predictor.use_stat_xgb}")
    print(f"XGB rolling loaded: {predictor.use_xgb}")
    print()

    # Teams from the latest screenshot
    test_names = [
        'Missouri St Bears',
        'Oklahoma St Cowboys',
        'Central Arkansas Bears',
        'Vanderbilt Commodores',
        'Boston College Eagles',
        "Florida Int'l Golden Panthers",
        'Omaha Mavericks',
        'Nebraska Cornhuskers',
        'Cincinnati Bearcats',
        'Western Kentucky Hilltoppers',
        'Coastal Carolina Chanticleers',
        'NC State Wolfpack',
    ]

    for name in test_names:
        resolved_id = predictor._resolve_team_id(name)
        bat = stats_dir / f"{resolved_id}_batting.csv"
        pit = stats_dir / f"{resolved_id}_pitching.csv"
        exists = bat.exists() or pit.exists()
        stats = await predictor.get_team_stats(name)
        rpg = stats.get('runs_per_game', 0) if stats else 'N/A'
        print(f"{name:40} => {resolved_id:35} | files={'OK' if exists else 'MISSING':7} | rpg={rpg}")

    # Test a full prediction
    print("\n--- Sample Prediction: Oklahoma St vs Missouri St ---")
    result = await predictor.predict_game('Oklahoma St Cowboys', 'Missouri St Bears')
    for k, v in result.items():
        print(f"  {k}: {v}")

asyncio.run(main())
