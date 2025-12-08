#!/usr/bin/env python3
"""
Data verification script for Sports ML Service.

This script validates that all required data files are present, properly formatted,
and ready for training.

Usage:
    python scripts/verify_data.py      # Verify all data
python scripts/verify_data.py --sport nba  # Verify only NBA
    python scripts/verify_data.py --report    # Generate detailed report
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
import json
from datetime import datetime
import logging

try:
    import pandas as pd
except ImportError:
    print("pandas required. Install with: pip install pandas")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# Expected data files with validation rules
EXPECTED_FILES = {
    "nba": {
        "data/nba/box_scores/PlayerStatistics.csv": {
   "required_columns": ["Player", "Year", "Points", "Rebounds", "Assists"],
            "min_rows": 1000,
            "size_range_mb": (250, 350)
        },
      "data/nba/box_scores/TeamStatistics.csv": {
            "required_columns": ["Team", "Year", "Points", "Wins", "Losses"],
            "min_rows": 100,
            "size_range_mb": (20, 40)
   },
        "data/nba/box_scores/Games.csv": {
         "required_columns": ["Date", "HomeTeam", "AwayTeam", "HomeScore", "AwayScore"],
            "min_rows": 100,
 "size_range_mb": (5, 15)
    }
    },
    "nfl": {
        "data/nfl/team_stats/nfl_team_stats_2002-2024.csv": {
            "required_columns": ["Team", "Year", "Wins", "Losses", "Points"],
            "min_rows": 100,
    "size_range_mb": (0.5, 5)
  }
  }
}


class DataValidator:
    """Validates data files for Sports ML Service."""
    
def __init__(self):
        self.results = {}
        self.errors = []
        self.warnings = []
    
    def get_file_size_mb(self, filepath: Path) -> float:
      """Get file size in MB."""
        if not filepath.exists():
      return 0
   return filepath.stat().st_size / (1024 * 1024)
    
    def check_file_exists(self, filepath: Path) -> Tuple[bool, str]:
        """Check if file exists."""
   if filepath.exists():
     return True, f"? File exists"
        return False, f"? File not found"
    
    def check_file_size(self, filepath: Path, expected_range: Tuple[float, float]) -> Tuple[bool, str]:
        """Check file size is within expected range."""
        size_mb = self.get_file_size_mb(filepath)
     min_size, max_size = expected_range
  
        if min_size <= size_mb <= max_size:
      return True, f"? Size OK: {size_mb:.2f} MB"
    else:
self.warnings.append(f"{filepath.name}: Size {size_mb:.2f} MB outside expected range ({min_size}-{max_size} MB)")
  return False, f"? Size {size_mb:.2f} MB (expected {min_size}-{max_size} MB)"
    
    def check_csv_format(self, filepath: Path) -> Tuple[bool, str]:
        """Check if file is valid CSV."""
     try:
            df = pd.read_csv(filepath, nrows=10)
            return True, f"? CSV format valid"
        except Exception as e:
            self.errors.append(f"{filepath.name}: Invalid CSV format - {e}")
  return False, f"? Invalid CSV: {str(e)[:50]}"
    
    def check_required_columns(self, filepath: Path, required_cols: List[str]) -> Tuple[bool, str]:
        """Check if CSV has required columns."""
        try:
            df = pd.read_csv(filepath, nrows=1)
  missing = [col for col in required_cols if col not in df.columns]
        
     if not missing:
    return True, f"? Required columns present"
    else:
             self.warnings.append(f"{filepath.name}: Missing columns: {missing}")
     return False, f"? Missing columns: {missing}"
        except Exception as e:
   self.errors.append(f"{filepath.name}: Could not check columns - {e}")
            return False, f"? Error checking columns"
    
    def check_row_count(self, filepath: Path, min_rows: int) -> Tuple[bool, str]:
        """Check if CSV has minimum rows."""
    try:
            df = pd.read_csv(filepath)
            row_count = len(df)
    
       if row_count >= min_rows:
   return True, f"? Row count OK: {row_count} rows"
    else:
       self.warnings.append(f"{filepath.name}: Only {row_count} rows (min {min_rows})")
     return False, f"? Only {row_count} rows (min {min_rows})"
        except Exception as e:
 self.errors.append(f"{filepath.name}: Could not check rows - {e}")
    return False, f"? Error checking rows"
    
    def check_null_values(self, filepath: Path) -> Tuple[bool, str]:
        """Check for excessive null values."""
        try:
    df = pd.read_csv(filepath)
       null_pct = (df.isnull().sum().sum() / (len(df) * len(df.columns))) * 100
            
  if null_pct < 10:
      return True, f"? Null values OK: {null_pct:.1f}%"
     elif null_pct < 25:
             self.warnings.append(f"{filepath.name}: {null_pct:.1f}% null values")
     return True, f"? {null_pct:.1f}% null values (acceptable)"
            else:
      self.errors.append(f"{filepath.name}: {null_pct:.1f}% null values (excessive)")
    return False, f"? {null_pct:.1f}% null values"
    except Exception as e:
       self.warnings.append(f"{filepath.name}: Could not check null values - {e}")
            return True, f"? Could not check"
    
    def validate_sport(self, sport: str) -> bool:
        """Validate all files for a sport."""
     if sport not in EXPECTED_FILES:
         logger.warning(f"Unknown sport: {sport}")
            return False
 
        logger.info(f"\n{'='*80}")
        logger.info(f"VALIDATING {sport.upper()} DATA")
     logger.info(f"{'='*80}")
      
        sport_valid = True
        files_config = EXPECTED_FILES[sport]
        
        for file_path, validation_rules in files_config.items():
            filepath = REPO_ROOT / file_path
    logger.info(f"\n?? {filepath.name}")
            
    # Check exists
            exists, msg = self.check_file_exists(filepath)
   logger.info(f"  {msg}")
            
     if not exists:
      sport_valid = False
    continue
     
     # Check size
          size_ok, msg = self.check_file_size(filepath, validation_rules.get("size_range_mb", (0, float('inf'))))
            logger.info(f"  {msg}")
            
     # Check format
   format_ok, msg = self.check_csv_format(filepath)
        logger.info(f"  {msg}")
            
 if not format_ok:
         sport_valid = False
continue
         
  # Check required columns
   cols_ok, msg = self.check_required_columns(filepath, validation_rules.get("required_columns", []))
        logger.info(f"  {msg}")
      
            # Check row count
      rows_ok, msg = self.check_row_count(filepath, validation_rules.get("min_rows", 1))
            logger.info(f"  {msg}")
         
    # Check null values
            nulls_ok, msg = self.check_null_values(filepath)
  logger.info(f"  {msg}")
       
          if not all([size_ok, format_ok, cols_ok, rows_ok]):
           sport_valid = False
        
        self.results[sport] = sport_valid
      return sport_valid
    
    def generate_report(self) -> Dict:
        """Generate validation report."""
        report = {
  "timestamp": datetime.now().isoformat(),
            "status": "PASS" if all(self.results.values()) else "FAIL",
    "results_by_sport": self.results,
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": {
     "total_sports": len(self.results),
 "passed": sum(1 for v in self.results.values() if v),
    "failed": sum(1 for v in self.results.values() if not v)
            }
        }
        return report
    
    def print_summary(self):
        """Print validation summary."""
        logger.info(f"\n{'='*80}")
   logger.info("VALIDATION SUMMARY")
        logger.info(f"{'='*80}")
        
        for sport, valid in self.results.items():
            status = "? PASS" if valid else "? FAIL"
     logger.info(f"{status}: {sport.upper()}")
        
        if self.warnings:
            logger.warning(f"\n? {len(self.warnings)} warning(s):")
  for warning in self.warnings:
       logger.warning(f"  - {warning}")
  
if self.errors:
         logger.error(f"\n? {len(self.errors)} error(s):")
            for error in self.errors:
     logger.error(f"  - {error}")
 
        all_valid = all(self.results.values())
   if all_valid:
          logger.info("\n? All data validated successfully! Ready to train models.")
else:
 logger.error("\n? Data validation failed. Run setup_data.py to download missing files.")
      logger.info(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
    description="Validate Sports ML Service data files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/verify_data.py      # Verify all sports
  python scripts/verify_data.py --sport nba  # Verify only NBA
  python scripts/verify_data.py --report    # Save detailed report
        """
    )
    
  parser.add_argument(
        "--sport",
  choices=["nba", "nfl", "nascar"],
        help="Specific sport to validate"
    )
    parser.add_argument(
        "--report",
        action="store_true",
  help="Save detailed JSON report"
    )
 
    args = parser.parse_args()
    
    validator = DataValidator()
    
    sports = [args.sport] if args.sport else list(EXPECTED_FILES.keys())
    
    for sport in sports:
        validator.validate_sport(sport)
    
    validator.print_summary()
    
    if args.report:
        report = validator.generate_report()
        report_path = DATA_DIR / "validation_report.json"
        with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
        logger.info(f"Report saved to: {report_path}")
    
    # Exit with appropriate code
    all_valid = all(validator.results.values())
    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
  main()
