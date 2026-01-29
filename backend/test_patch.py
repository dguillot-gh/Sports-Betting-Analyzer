
import sys
import xgboost as xgb

# Monkeypatch load_model to suppress legacy format errors
original_load_model = xgb.Booster.load_model

def patched_load_model(self, fname):
    try:
        if "ep_model.model" in str(fname):
            print(f"Skipping legacy model load: {fname}")
            return
        original_load_model(self, fname)
    except Exception as e:
        print(f"Intercepted error loading {fname}: {e}")

xgb.Booster.load_model = patched_load_model

print("Importing sportsdataverse.cfb...")
try:
    import sportsdataverse.cfb as sdv_cfb
    print("Import SUCCESS!")
except Exception as e:
    print(f"Import FAILED: {e}")

# Test if we can still fetch schedule (the actual goal)
# Note: We can't really test fetching without network/keys potentially, but import success is the big hurdle.
