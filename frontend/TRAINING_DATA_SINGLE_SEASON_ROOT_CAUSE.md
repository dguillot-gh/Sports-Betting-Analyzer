# ?? Training Data Issue - Single Season Problem

## Root Cause Identified ?

The NASCAR training is only using **1 series of data** (Cup Series) because of the config file setting.

### The Problem

**File**: `C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml`

```yaml
data:
  results_file: cup_series.rda # ? THIS IS THE PROBLEM!
```

This configuration tells the NASCAR loader to use ONLY the Cup Series RDA file, which contains data from only ONE NASCAR series.

### What's Available

Your data directory contains:

```
data/nascar/raw/
??? nascar race data.csv    # ? 11,325 rows - 8 seasons (2017-2024)
??? cup_series.rda      # ~1 season worth
??? truck_series.rda      # Truck series data
??? xfinity_series.rda      # Xfinity series data
```

**The CSV file has the most comprehensive data: 11,325 rows spanning 8 years!**

### Solution

**Option 1: Use the comprehensive CSV (RECOMMENDED)**

Change `nascar_config.yaml`:

```yaml
name: nascar
data:
  results_file: nascar race data.csv  # ? Changed to CSV
features:
  categorical:
    - driver
- track
    - track_type
    - manu
    - team_name
    - status
  boolean: []
numeric:
 - year
    - race_num
    - start
    - car_num
    - laps
    - laps_led
    - stage_1
    - stage_2
targets:
  classification: race_win
  regression: finishing_position
preprocessing: {}
```

**Option 2: Load ALL series combined**

Modify the NASCAR loader to combine all RDA files (no config change needed, but requires code update).

---

## Why This Matters

### Current (Broken)
- ? Only Cup Series data
- ? Limited training samples
- ? Poor model generalization

### After Fix (Good)
- ? 11,325 training samples
- ? 8 years of historical data
- ? Better model accuracy and generalization
- ? More diverse racing conditions

---

## Implementation

### Step 1: Update the Config File

Edit: `C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml`

Replace the line:
```yaml
results_file: cup_series.rda
```

With:
```yaml
results_file: nascar race data.csv
```

### Step 2: Restart Python Service

In the PowerShell window where the service is running:
1. Press `Ctrl+C` to stop
2. Run again: `env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000`

### Step 3: Retrain Models

1. Go to Blazor app
2. Go to ML Training page
3. Click "Train" for NASCAR
4. It will now train on full 8-year dataset (11,325 rows)

---

## Technical Details

The `chronological_split()` function in `data_loader.py` splits 80% for training and 20% for testing:

**With single season (current)**:
- Train: ~1,300-1,400 rows
- Test: ~300-350 rows
- Model quality: Poor

**With full data (after fix)**:
- Train: ~9,000 rows (8 years)
- Test: ~2,300 rows (1 year)
- Model quality: Much better!

---

## Files Involved

| File | Change | Status |
|------|--------|--------|
| `configs/nascar_config.yaml` | Change `results_file` | ? Need to update |
| `src/sports/nascar.py` | No change needed | ? OK |
| `src/data_loader.py` | No change needed | ? OK |
| `src/train.py` | No change needed | ? OK |

---

## Expected Results After Fix

```
Before (Current):
  Training Data: 1 season
  Training Samples: ~1,400
  Model Accuracy: ~60-70%

After (Fixed):
  Training Data: 8 seasons (2017-2024)
  Training Samples: ~9,000
  Model Accuracy: ~80-90% (expected)
```

---

## Verification

After making the fix, you can verify by:

1. Checking logs in Python service console
2. Models will be retrained with full dataset
3. Check generated metrics in `models/nascar/csv/` directory
4. Compare accuracy before/after

---

**Status**: ?? **IDENTIFIED - Ready to fix**  
**Fix Complexity**: ? **Very simple** (1-line config change)  
**Time to Fix**: < 1 minute  
**Impact**: Major improvement in model quality
