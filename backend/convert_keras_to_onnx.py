import os
import tensorflow as tf
import tf2onnx
import onnx
from pathlib import Path

# Paths
BASE_DIR = Path(r'c:\Users\dguil\source\repos\PythonMLService\backend\scripts\nba_ml_reference\Models\NN_Models')

def convert_models():
    if not BASE_DIR.exists():
        print(f"Error: Directory {BASE_DIR} not found.")
        return

    keras_files = list(BASE_DIR.glob("*.keras"))
    if not keras_files:
        print("No .keras files found.")
        return

    print(f"Found {len(keras_files)} Keras models.")

    for k_path in keras_files:
        print(f"\nProcessing {k_path.name}...")
        try:
            # Load Keras model
            model = tf.keras.models.load_model(k_path)
            
            # Convert to ONNX
            # opset 13 is widely supported
            onnx_model, _ = tf2onnx.convert.from_keras(model, opset=13)
            
            # Save
            output_path = k_path.with_suffix(".onnx")
            onnx.save_model(onnx_model, str(output_path))
            print(f"Success: Saved to {output_path.name}")
            
        except Exception as e:
            print(f"Failed to convert {k_path.name}: {e}")

if __name__ == "__main__":
    convert_models()
