# ?? Manual Fix Guide - Exact Lines to Change

## Current Status

? **Config Fix Complete**: `configs/nascar_config.yaml` updated to use full CSV dataset (8 years)  
?? **App.py Partial**: Need to add 3 lines to handle NaN values

---

## What to Do Now

### File: `C:\Users\dguil\source\repos\PythonMLService\api\app.py`

### Change 1: NASCAR Data Endpoint (around line 130-145)

**FIND THIS**:
```python
@app.get('/nascar/data')
def nascar_data(series: Optional[str] = None, limit: int = 1000,
  year_min: Optional[int] = None, year_max: Optional[int] = None,
  track_type: Optional[str] = None):
    sport, _ = build_nascar(series)
    df = load_sport_data(sport)
    
    # ... (some filtering code)
 
    out = df.head(limit)
  return {
     'columns': out.columns.tolist(),
        'rows': out.to_dict(orient='records'),
  'total_rows': int(len(df))
    }
```

**REPLACE WITH**:
```python
@app.get('/nascar/data')
def nascar_data(series: Optional[str] = None, limit: int = 1000,
        year_min: Optional[int] = None, year_max: Optional[int] = None,
          track_type: Optional[str] = None):
    sport, _ = build_nascar(series)
df = load_sport_data(sport)
    
    # ... (some filtering code - DON'T CHANGE THIS PART)
    
    out = df.head(limit)
    out = clean_for_json(out)  # ? ADD THIS LINE
    rows = out.to_dict(orient='records')  # ? CHANGE FROM: 'rows': out.to_dict(orient='records'),
return {
   'columns': out.columns.tolist(),
'rows': rows,  # ? CHANGE FROM: 'rows': out.to_dict(orient='records'),
     'total_rows': int(len(df))
    }
```

**What Changed**:
- Line before `return`: Added `out = clean_for_json(out)`
- Separate the dict call: `rows = out.to_dict(orient='records')`
- Return statement: Changed `'rows': out.to_dict(...)` to `'rows': rows`

---

### Change 2: NFL Data Endpoint (around line 200-210)

**FIND THIS**:
```python
@app.get('/nfl/data')
def nfl_data(limit: int = 1000, season_min: Optional[int] = None, season_max: Optional[int] = None):
    s = get_nfl()
    df = load_sport_data(s)
    if 'schedule_season' in df.columns:
        if season_min is not None:
  df = df[df['schedule_season'] >= season_min]
        if season_max is not None:
            df = df[df['schedule_season'] <= season_max]
    out = df.head(limit)
    return {'columns': out.columns.tolist(), 'rows': out.to_dict(orient='records'), 'total_rows': int(len(df))}
```

**REPLACE WITH**:
```python
@app.get('/nfl/data')
def nfl_data(limit: int = 1000, season_min: Optional[int] = None, season_max: Optional[int] = None):
    s = get_nfl()
 df = load_sport_data(s)
    if 'schedule_season' in df.columns:
 if season_min is not None:
            df = df[df['schedule_season'] >= season_min]
        if season_max is not None:
            df = df[df['schedule_season'] <= season_max]
    out = df.head(limit)
    out = clean_for_json(out)  # ? ADD THIS LINE
    rows = out.to_dict(orient='records')  # ? ADD THIS LINE
    return {'columns': out.columns.tolist(), 'rows': rows, 'total_rows': int(len(df))}  # ? CHANGE 'rows': out.to_dict(...) to 'rows': rows
```

**What Changed**:
- Line before `return`: Added `out = clean_for_json(out)`
- Line before `return`: Added `rows = out.to_dict(orient='records')`
- Return statement: Changed `out.to_dict(orient='records')` to `rows`

---

## How to Edit

### Option A: Visual Studio Code
1. Open `api/app.py`
2. Press `Ctrl+G` ? Go to line number
3. Make changes manually
4. Save with `Ctrl+S`

### Option B: Visual Studio
1. Open the file in Solution Explorer
2. Find the methods
3. Make edits
4. Save

### Option C: Terminal (if comfortable with Python)
```powershell
cd C:\Users\dguil\source\repos\PythonMLService

# Start editing
notepad api/app.py
```

---

## After Editing

1. **Save the file**
2. **Don't restart the service** - it auto-reloads
3. **Look at Python service console** - you'll see "Reload process" message
4. **Refresh Blazor app** (F5)
5. **Try browsing datasets** - should work now!

---

## Why These Changes

**Before** (? Broken):
```python
return {
    'rows': out.to_dict(orient='records'),  # NaN values in dict ? JSON fails
}
```

**After** (? Fixed):
```python
out = clean_for_json(out)  # Convert NaN ? None
rows = out.to_dict(orient='records')  # Safe to JSON
return {
    'rows': rows  # None values serialize fine
}
```

---

## Verification

After editing and saving:

1. Python service should show:
```
   INFO:     Uvicorn running on http://0.0.0.0:8000
   INFO:     Application updated
   ```

2. Blazor app - go to MLTraining page ? Browse Datasets ? Select NASCAR ? View Data
   - ? Should see data rows
   - ? Should NOT see: "ValueError: Out of range float values are not JSON compliant: nan"

---

## Estimated Time

- Finding the endpoints: 1-2 minutes
- Making edits: 1-2 minutes
- Saving: 10 seconds
- Service auto-reload: 5 seconds
- **Total: ~5 minutes**

---

## If You Get Stuck

Just tell me you made the edits and I'll verify they're correct!

The key is:
1. Add `out = clean_for_json(out)` before the return
2. Change `out.to_dict(...)` to just `rows` in the return statement
3. Save

That's it! ??

