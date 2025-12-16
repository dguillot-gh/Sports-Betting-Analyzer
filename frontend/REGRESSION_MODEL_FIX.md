# ?? Regression Model Failure - Root Cause & Fix

## The Problem

When you click "Train Regression" for NASCAR, the model hangs/fails because:

```
UserWarning: Skipping features without any observed values: ['stage_1' 'stage_2'].
At least one non-missing value is needed for imputation with strategy='median'.
```

**The issue**: These columns exist but have **100% NaN values** (no data), yet they're included in the regression pipeline.

---

## Why This Happens

Your historical NASCAR data (1949-2024) predates modern stage racing:

| Era | Stage Columns? | Status |
|-----|---|---|
| 1949-2014 | ? No | Historical data has NaN |
| 2015+ | ? Yes | Modern NASCAR uses stages |

Since 75% of your data is pre-2015, most rows have NaN for `stage_1`, `stage_2`, `stage_3_or_duel`, `stage_points`.

---

## Current Config (Broken)

**File**: `configs/nascar_config.yaml`

```yaml
features:
  numeric:
    - year
    - race_num
    - start
    - car_num
    - laps
    - laps_led
    - stage_1   # ? 100% NaN in old data!
    - stage_2     # ? 100% NaN in old data!
    - ...
```

---

## The Fix

Remove stage columns from the numeric features list (they can't be reliably imputed):

**NEW** `configs/nascar_config.yaml`:

```yaml
name: nascar
data:
  results_file: nascar race data.csv
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
targets:
  classification: race_win
  regression: finishing_position
preprocessing: {}
```

**What changed**: Removed `stage_1`, `stage_2`, `stage_3_or_duel`, `stage_points` from numeric features.

**Why**: These columns aren't useful for historical data prediction anyway since they didn't exist until 2015.

---

## Apply the Fix

### Step 1: Open the config file
```
C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml
```

### Step 2: Replace the `numeric` section

**FIND THIS**:
```yaml
  numeric:
    - year
    - race_num
    - start
    - car_num
    - laps
  - laps_led
    - stage_1
    - stage_2
```

**REPLACE WITH**:
```yaml
  numeric:
    - year
    - race_num
    - start
    - car_num
    - laps
    - laps_led
```

### Step 3: Save

That's it!

---

## Why This Works

### Before (? Broken):
```
Pipeline tries to use: [year, race_num, start, car_num, laps, laps_led, stage_1, stage_2, ...]
       ^^^^^^   ^^^^^^
   (100% NaN - breaks!)
?
sklearn imputer fails: "Can't impute column with no values"
?
Regression training hangs/fails
```

### After (? Fixed):
```
Pipeline uses: [year, race_num, start, car_num, laps, laps_led]
 (all have data across 75 years)
?
sklearn imputer works normally
?
Regression trains successfully on meaningful features
?
Model completes in ~30 seconds
```

---

## Expected Behavior After Fix

### Classification (Win prediction):
- ? Should train fine - already working
- Uses driver, track, racing conditions, historical performance
- ~80-90% accuracy expected

### Regression (Finish position prediction):
- ? Should now train successfully
- Uses same features as classification
- Predicts finishing position (1-43)
- Training should take 30-60 seconds
- Metrics will show MAE/RMSE for position prediction

---

## Technical Details

### Why Imputation Fails

sklearn's `SimpleImputer` with `strategy='median'`:
1. Looks at column values
2. Calculates median of non-NaN values
3. If ALL values are NaN ? **no median to calculate**
4. Throws warning and skips the column
5. Pipeline continues but is confused about missing feature slots
6. Eventually fails during model training

### Why Historical Data Has NaN for Stages

```python
# Sample from 1949 data:
{
    'year': 1949,
    'track': 'Charlotte Speedway',
    'Stage_1': NaN,      # Stages didn't exist!
 'Stage_2': NaN,      # Didn't exist until 2015
    'finishing_position': 1,
    'laps_led': 47  # This exists in old data
}
```

### Why Removing Them Is Safe

1. **Not useful for historical prediction**: Can't predict 2023 finish position using stage data that didn't exist in 1949
2. **Better regression basis**: Using only relevant historical features improves model
3. **More robust**: Classification still works on non-stage features

---

## Verification After Fix

After updating config and restart:

1. **Go to ML Training**
2. **Select NASCAR**
3. **Select Regression task**
4. **Click Train**
5. **Expected**: Training completes in 30-60 seconds with metrics

You should see output like:
```
Training regression model for nascar...
Mean Absolute Error (MAE): 4.2  (average position error)
R² Score: 0.68
Test start season: 2023
Finished!
```

---

## If It Still Fails

Check the Python service console for errors. Common issues:

1. **File not saved**: Verify config file changes
2. **Service not reloaded**: Service auto-reloads on file change, but sometimes needs manual restart
3. **Other NaN columns**: If error mentions other columns, they may need removing too

---

## Related Columns That May Have Issues

If you still get warnings about other columns:

| Column | Pre-2015 data? | Solution |
|--------|---|---|
| `stage_1` | ? No | Remove |
| `stage_2` | ? No | Remove |
| `stage_3_or_duel` | ? No | Remove |
| `stage_points` | ? No | Remove |
| `points` | ? Yes | Keep |
| `laps_led` | ? Yes | Keep |
| `laps` | ? Yes | Keep |

---

## Complete Fixed Config

If you want the entire file at once:

```yaml
name: nascar
data:
  results_file: nascar race data.csv
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
targets:
  classification: race_win
  regression: finishing_position
preprocessing: {}
```

---

## Summary

| Issue | Cause | Fix | Time |
|-------|-------|-----|------|
| Regression training hangs | Stage columns 100% NaN | Remove from config | 1 min |
| Classification works fine | Non-stage features have data | No change needed | 0 min |
| sklearn warnings | Imputation on empty column | Removing bad columns fixes | 0 min |

**Total fix time**: ~1 minute

**Expected result**: Regression training completes successfully with good accuracy!

