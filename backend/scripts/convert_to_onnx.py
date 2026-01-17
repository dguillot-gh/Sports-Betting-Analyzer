import os
import sys
from pathlib import Path

# Try to import heavy dependencies (only needed during conversion)
try:
    import numpy as np
    # Monkey-patch np.object for compatibility with newer numpy versions and older tf2onnx
    if not hasattr(np, "object"):
        np.object = object
        
    import tensorflow as tf
    import tf2onnx
    import onnx
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "nba_ml_reference" / "Models" / "NN_Models"

def convert_keras_to_onnx(model_path):
    print(f"Converting {model_path.name} to ONNX...")
    onnx_path = model_path.with_suffix(".onnx")
    
    try:
        # Load model with compile=False to avoid needing custom objects/losses
        model = tf.keras.models.load_model(str(model_path), compile=False)
        
        # Determine input signature (usually (None, 106) or (None, 107))
        spec = (tf.TensorSpec((None, *model.input_shape[1:]), tf.float32, name="input"),)
        
        # Convert
        model_proto, _ = tf2onnx.convert.from_keras(model, input_signature=spec, opset=13)
        
        # Save
        with open(onnx_path, "wb") as f:
            f.write(model_proto.SerializeToString())
            
        print(f"  [OK] Saved to {onnx_path.name}")
        return True
    except Exception as e:
        print(f"  [FAIL] Conversion error: {e}")
        return False

def main():
    if not TF_AVAILABLE:
        print("TensorFlow or tf2onnx not found. Skipping conversion.")
        return 1
        
    if not MODELS_DIR.exists():
        print(f"Models directory {MODELS_DIR} not found.")
        return 1
        
    models = list(MODELS_DIR.glob("*.keras")) + list(MODELS_DIR.glob("*.h5"))
    if not models:
        print("No .keras or .h5 models found to convert.")
        return 0
        
    success_count = 0
    for m in models:
        if convert_keras_to_onnx(m):
            success_count += 1
            
    print(f"\nFinished. Successfully converted {success_count}/{len(models)} models.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
