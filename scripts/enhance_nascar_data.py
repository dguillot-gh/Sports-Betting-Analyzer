"""
NASCAR Feature Engineering Script - All Series
Processes Cup, Truck, and Xfinity series data
Run weekly when new data is published
Usage: python scripts/enhance_nascar_data.py
"""
from pathlib import Path
import sys

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from nascar_enhancer import enhance_all_series

# Configuration
DATA_DIR = Path(__file__).parent.parent / "data" / "nascar"

def main():
    print("="*60)
    print("NASCAR Feature Engineering - All Series")
    print("="*60)
    print(f"Data directory: {DATA_DIR}")
    
    # Ensure output directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    results = enhance_all_series(DATA_DIR)
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    all_success = True
    for series, result in results.items():
        status = "✅ SUCCESS" if result['success'] else "❌ FAILED"
        print(f"{series:<20} {status}")
        if not result['success']:
            print(f"  Error: {result['message']}")
            all_success = False
            
    if all_success:
        print("\n🎉 All series processed successfully!")
    else:
        print("\n⚠️ Some series failed to process.")

if __name__ == "__main__":
    main()