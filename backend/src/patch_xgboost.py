
import logging
import xgboost as xgb

logger = logging.getLogger(__name__)

# Monkeypatch load_model to suppress legacy format errors
# This allows sportsdataverse to import even with XGBoost > 2.0
# The EP models will be broken, but schedule/stats fetching will work.

original_load_model = xgb.Booster.load_model

def patched_load_model(self, fname):
    fname_str = str(fname)
    # Check for sportsdataverse legacy models
    if "ep_model.model" in fname_str or "wp_spread.model" in fname_str or "qbr_model.model" in fname_str:
        logger.warning(f"Monkeypatch: Skipping legacy sportsdataverse model load: {fname}")
        return

    try:
        original_load_model(self, fname)
    except Exception as e:
        # If it's a binary format error, just log and skip
        if "binary format" in str(e) and "sportsdataverse" in fname_str:
             logger.error(f"Monkeypatch: Intercepted binary format error for {fname}: {e}")
             return
        raise e

xgb.Booster.load_model = patched_load_model
logger.info("XGBoost load_model patched for legacy support.")
