
import asyncio
import sys
import os
import pandas as pd
import numpy as np
import xgboost as xgb
from scripts.kyleskom_adapter import get_kyleskom_predictor

async def main():
    print("=== O/U Feature Isolation Analysis ===")
    
    predictor = get_kyleskom_predictor()
    predictor.load_models()
    
    def get_ou_pred(data_vec):
        # Use simple model predict instead of wrapper for raw check
        dmat = xgb.DMatrix(data_vec)
        raw_res = predictor.xgb_ou.predict(dmat)[0]
        # raw_res is [prob0, prob1]
        return {
            'pick': 'OVER' if raw_res[1] > raw_res[0] else 'UNDER',
            'over_prob': raw_res[1],
            'under_prob': raw_res[0]
        }

    # Isolation Test: All zeros except feature 104
    print("\n[Test 3] Isolation: All Zeros except Index 104")
    for val in [10.0, 225.0, 1000.0]:
        data_iso = np.zeros((1, 107))
        data_iso[0, 104] = val
        ou = get_ou_pred(data_iso)
        print(f"Line: {val:6.1f} | Pick: {ou['pick']:5} | Over Prob: {ou['over_prob']:.4f} | Under Prob: {ou['under_prob']:.4f}")

    # Isolation Test: All zeros except feature 0 (maybe it's there?)
    print("\n[Test 4] Isolation: All Zeros except Index 0")
    for val in [10.0, 225.0, 1000.0]:
        data_iso = np.zeros((1, 107))
        data_iso[0, 0] = val
        ou = get_ou_pred(data_iso)
        print(f"Line: {val:6.1f} | Pick: {ou['pick']:5} | Over Prob: {ou['over_prob']:.4f} | Under Prob: {ou['under_prob']:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
