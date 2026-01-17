import os
import sys
import re
from pathlib import Path

def diagnose():
    print("--- NN ENVIRONMENT DIAGNOSTIC ---")
    
    # 1. Check Path
    current_dir = Path(__file__).resolve().parent
    models_dir = current_dir / 'nba_ml_reference' / 'Models' / 'NN_Models'
    
    print(f"Current Dir: {current_dir}")
    print(f"Models Dir: {models_dir}")
    print(f"Models Dir Exists: {models_dir.exists()}")
    
    if models_dir.exists():
        print("Files in NN_Models:")
        for f in models_dir.glob("*"):
            print(f" - {f.name} ({f.stat().st_size} bytes)")
    
    # 2. Check Imports
    print("\n--- IMPORT CHECKS ---")
    try:
        import numpy
        print(f"Numpy Version: {numpy.__version__}")
    except ImportError:
        print("Numpy NOT FOUND")
        
    try:
        import onnxruntime as ort
        print(f"ONNX Runtime Version: {ort.__version__}")
        ONNX_AVAIL = True
    except ImportError:
        print("ONNX Runtime NOT FOUND")
        ONNX_AVAIL = False
        
    # 3. Test Loading
    if ONNX_AVAIL and models_dir.exists():
        print("\n--- LOADING TEST ---")
        onnx_files = list(models_dir.glob("*.onnx"))
        if not onnx_files:
            print("No .onnx files found to test load.")
        else:
            for of in onnx_files:
                try:
                    print(f"Attempting to load {of.name}...")
                    sess = ort.InferenceSession(str(of))
                    print(f" [OK] Successfully loaded {of.name}")
                    print(f"      Inputs: {[i.name for i in sess.get_inputs()]}")
                except Exception as e:
                    print(f" [FAIL] Error loading {of.name}: {e}")

if __name__ == "__main__":
    diagnose()
