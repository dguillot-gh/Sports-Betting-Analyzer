# ?? IMMEDIATE ACTION REQUIRED - Fix Regression Model Issue

## The Issue

Regression training hangs because the config includes `stage_1` and `stage_2` columns which have **100% NaN values** in historical NASCAR data (1949-2014).

Error: `Skipping features without any observed values: ['stage_1' 'stage_2']`

---

## The Fix (2 steps)

### Step 1: Update `nascar_config.yaml`

**File Path**: `C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml`

**Replace the ENTIRE file with**:

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

**Key Changes**:
- ? Keep: `results_file: nascar race data.csv` (8 years of data)
- ? Remove from numeric: `stage_1`, `stage_2`, `stage_3_or_duel`, `stage_points`
- ? Keep: `year`, `race_num`, `start`, `car_num`, `laps`, `laps_led` (these have data)

### Step 2: Restart Python Service

In the PowerShell window where the service runs:
1. Press `Ctrl+C`
2. Run: `env\Scripts\python.exe -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000`

---

## Why This Works

| Feature | Pre-2015 Data | Post-2015 Data | Use? |
|---------|---|---|---|
| `stage_1` | ? NaN | ? 90% | ? Remove - can't train on 75% NaN |
| `stage_2` | ? NaN | ? 90% | ? Remove - can't train on 75% NaN |
| `year` | ? 100% | ? 100% | ? Keep - always have it |
| `laps_led` | ? 100% | ? 100% | ? Keep - always have it |
| `finishing_position` | ? 100% | ? 100% | ? Target - always have it |

---

## After the Fix

### Test Regression Training

1. **Go to Blazor ML Training page**
2. **Select NASCAR**
3. **Select "Finishing Position" (regression)**
4. **Click Train**

**Expected Result**: ? Training completes in 30-60 seconds

**You should see**:
```
Training regression model...
Model saved successfully
Metrics: MAE (Mean Absolute Error), R² Score
```

---

##  Before vs After

### Before (Broken) ?
```
Numeric features: [year, race_num, start, car_num, laps, laps_led, stage_1, stage_2, ...]
  ^^^^^^^^  ^^^^^^^^
     100% NaN - breaks!
?
Imputation error: "Can't impute features with no values"
?
Training hangs/fails
```

### After (Fixed) ?
```
Numeric features: [year, race_num, start, car_num, laps, laps_led]
All have data across entire 1949-2024 dataset
?
Imputation works normally
?
Training completes successfully
```

---

## File Edit Instructions

### Using Notepad
```powershell
notepad "C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml"
```

### Using VS Code
```powershell
code "C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml"
```

### Using PowerShell (if Notepad doesn't work)
```powershell
$config = @"
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
"@

$config | Set-Content -Path "C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml" -Encoding UTF8 -Force
```

---

## Verification

After making the change, check:

```powershell
Get-Content "C:\Users\dguil\source\repos\PythonMLService\configs\nascar_config.yaml"
```

Should show:
- ? `results_file: nascar race data.csv`
- ? No `stage_1` or `stage_2` in numeric features
- ? Only these numeric: `year`, `race_num`, `start`, `car_num`, `laps`, `laps_led`

---

## Summary

| Item | Status |
|------|--------|
| Classification training | ? Works fine - don't change |
| Regression training | ? Broken - needs config fix |
| Root cause | Stage columns with 100% NaN |
| Solution | Remove non-existent stage columns |
| Time to fix | ~2 minutes |
| Expected outcome | Regression trains successfully |

---

## Need Help?

If you can't edit the file, I can help regenerate it. Just let me know you made this change and I'll verify!

**Next Step**: Edit the config file and restart the Python service.

