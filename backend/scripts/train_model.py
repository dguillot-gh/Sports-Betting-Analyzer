"""
Unified training script for all sports.
"""
import argparse
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install PyYAML")
    sys.exit(1)

from sports.nfl import NFLSport
from sports.nascar import NASCARSport
import train


def load_sport_config(sport_name: str) -> dict:
    """Load configuration for a sport."""
    # Resolve config relative to the project root (one level up from scripts/)
    project_root = Path(__file__).parent.parent
    config_path = project_root / 'configs' / f'{sport_name}_config.yaml'
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_sport_instance(sport_name: str):
    """Get sport instance based on name."""
    config = load_sport_config(sport_name)

    if sport_name == 'nfl':
        return NFLSport(config)
    elif sport_name == 'nascar':
        return NASCARSport(config)
    else:
        # For future sports, add elif conditions here
        # elif sport_name == 'nba':
        #     return NBASport(config)
        # elif sport_name == 'nascar':
        #     return NASCARSport(config)
        raise ValueError(f"Sport '{sport_name}' is not implemented yet. "
                        f"Available sports: nfl, nascar")


def parse_args():
    p = argparse.ArgumentParser(description='Train ML models for various sports.')
    p.add_argument('--sport', default='nfl', choices=['nfl', 'nascar'],
                   help='Which sport to train models for (default: nfl).')
    p.add_argument('--task', choices=['classification', 'regression'], default='classification',
                   help='Which task to train: classification (home team win) or regression (point differential).')
    p.add_argument('--out-dir', default=None,
                   help='Directory to save trained model and metrics. Defaults to models/{sport}.')
    p.add_argument('--test-start', type=int, default=None,
                   help='Season year where test set starts (e.g., 2015).')
    return p.parse_args()


def main():
    args = parse_args()

    # Set default output directory
    if args.out_dir is None:
        args.out_dir = f'models/{args.sport}'

    out_dir = Path(args.out_dir)

    try:
        # Get sport instance
        sport = get_sport_instance(args.sport)

        # Train and evaluate
        model_path, metrics_path, metrics = train.train_and_evaluate_sport(
            sport, args.task, out_dir, args.test_start
        )

        print(f"Saved model to: {model_path}")
        print(f"Saved metrics to: {metrics_path}")
        print("Metrics summary:")
        print(json.dumps(metrics, indent=2))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
