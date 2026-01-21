#!/usr/bin/env python3
"""
Final SHAP Fix Verification
Tests that the _load_models_v2 method properly loads and repairs corrupted models.
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).parent.parent))

from scripts.ncaab_predictor import NCAABPredictor

def test_shap_fix():
    print("=" * 60)
    print("SHAP FIX VERIFICATION")
    print("=" * 60)
    
    # 1. Initialize predictor
    print("\n1. Initializing NCAABPredictor...")
    predictor = NCAABPredictor()
    
    # 2. Check paths
    print(f"\n2. Checking model paths...")
    print(f"   ML Model: {predictor.ml_v2_path}")
    print(f"   Exists: {predictor.ml_v2_path.exists()}")
    
    # 3. Trigger lazy load (this should call _load_models_v2)
    print(f"\n3. Triggering lazy load...")
    ml_model = predictor.ml_model_v2
    
    if ml_model:
        print(f"   [OK] ML Model loaded successfully")
        
        # 4. Test prediction (will trigger SHAP)
        print(f"\n4. Testing prediction with SHAP...")
        try:
            result = predictor.predict_game("Duke", "North Carolina")
            
            print(f"\n5. Results:")
            print(f"   V2 Available: {result.get('v2_available', False)}")
            print(f"   V2 Win Prob: {result.get('v2_win_prob', 'N/A')}")
            
            factors = result.get('v2_factors', [])
            if factors:
                print(f"   [OK] SHAP Factors: {len(factors)} found")
                for f in factors[:3]:
                    print(f"      - {f['label']}: {f['impact']:.4f}")
                print("\n[SUCCESS] SHAP calculation completed without errors!")
            else:
                print(f"   [WARNING] No SHAP factors returned")
                
        except Exception as e:
            print(f"   [ERROR] SHAP Error: {e}")
            return False
    else:
        print(f"   [ERROR] Failed to load ML model")
        return False
    
    return True

if __name__ == "__main__":
    success = test_shap_fix()
    sys.exit(0 if success else 1)
