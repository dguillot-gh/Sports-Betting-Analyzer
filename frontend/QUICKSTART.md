# Quick Start Guide - Python ML Service Integration

## ?? Getting Started

### Step 1: Start the Python ML Service

```bash
# Navigate to the Python ML Service directory
cd C:\Users\dguil\source\repos\PythonMLService\mllearning

# Install dependencies (first time only)
python -m pip install -r requirements.txt

# Start the FastAPI server
python -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
```

**Expected Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Step 2: Run the Blazor Application

```bash
cd C:\Users\dguil\source\repos\SportsBettingAnalyzer
dotnet run
```

**Expected Output:**
```
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: https://localhost:5001
```

### Step 3: Access the ML Training Page

1. Navigate to `https://localhost:5001` in your browser
2. Look for **"ML Training"** in the left navigation menu (school icon)
3. You should see a green confirmation: **"Python ML Service connected"**

---

## ?? Using the ML Training Interface

### Dataset Explorer

1. **Select a Sport**: Click on "NFL", "NASCAR", or "NBA"
2. **View Dataset Info**: See total rows and available columns
3. **Preview Data**: Scroll through the sample data table

### Train a Model

1. **Select Sport**: Choose from dropdown (e.g., "NFL")
2. **Select Task**: 
   - **Classification**: Predict win/loss outcomes
   - **Regression**: Predict score differentials
3. **Configure Split** (Optional): Set test start season
4. **Click "Start Training"**: Watch the progress indicator
5. **Review Results**: See performance metrics when complete

### Available Models

| Sport | Training Data | Tasks |
|-------|---------------|-------|
| **NFL** | 1966-2024 (10K+ games) | Classification, Regression |
| **NASCAR** | 1972-2024 (5K+ races) | Classification, Regression |
| **NBA** | 1979-2024 (20K+ games) | Coming Soon |

---

## ?? Configuration

### Change Python Service URL

Edit `appsettings.json`:

```json
{
  "PythonMLService": {
    "BaseUrl": "http://your-server:8000",  // Change host/port here
    "TimeoutSeconds": 300,                  // Increase for large datasets
    "HealthCheckIntervalSeconds": 30        // How often to check service health
  }
}
```

---

## ?? Troubleshooting

### "Python ML Service is not available"

**Problem**: Red alert saying Python service is unavailable

**Solution**:
1. Verify Python service is running: `http://localhost:8000/docs`
2. Check firewall allows localhost connections
3. Verify port 8000 is not in use: `netstat -ano | findstr :8000`
4. Restart Python service

### "Timeout" during training

**Problem**: Training takes too long and times out

**Solution**:
1. Increase `TimeoutSeconds` in `appsettings.json` to 600 or higher
2. Use smaller datasets or custom test split
3. Check system resources (RAM, CPU)

### "No data available for selected sport"

**Problem**: Dataset preview shows no data

**Solution**:
1. Verify CSV/RDA files exist in Python service data directory:
   - `C:\Users\dguil\source\repos\PythonMLService\mllearning\data\`
2. Check Python service logs for data loading errors
3. Ensure Python requirements are fully installed: `pip install -r requirements.txt`

---

## ?? Data Files

### Location
```
C:\Users\dguil\source\repos\PythonMLService\mllearning\data\
??? nfl\raw\
?   ??? spreadspoke_scores.csv
?   ??? nfl_teams.csv
??? nascar\raw\
?   ??? nascar race data.csv
?   ??? cup_series.rda
? ??? truck_series.rda
?   ??? xfinity_series.rda
??? nba\raw\
    ??? (placeholder)
```

### Adding New Data

1. Place CSV or RDA files in the appropriate `data/{sport}/raw/` folder
2. Restart Python service - it will automatically detect new files
3. Refresh Blazor page and select sport to view new dataset

---

## ?? Typical Workflow

1. **Explore Data** (Dataset Explorer tab)
   - Select sport
   - Check available columns and sample data
 - Note data quality

2. **Train Model** (Train Model tab)
   - Choose task type (Classification/Regression)
   - Configure optional parameters
   - Start training
   - Monitor progress

3. **Review Results**
   - Check performance metrics
   - Note model accuracy/RMSE
   - Compare different configurations

4. **Use Model** (Coming Soon)
   - Make predictions on new data
   - Export model information
   - Track training history

---

## ?? Model Performance Metrics

### Classification Models
- **Accuracy**: Percentage of correct predictions
- **Precision**: True positives / (True positives + False positives)
- **Recall**: True positives / (True positives + False negatives)
- **F1-Score**: Harmonic mean of precision and recall

### Regression Models
- **MSE**: Mean Squared Error
- **RMSE**: Root Mean Squared Error (lower is better)
- **MAE**: Mean Absolute Error
- **R² Score**: Coefficient of determination (0-1, higher is better)

---

## ?? Tips & Best Practices

1. **Start Small**: Test with a single season first
2. **Check Data**: Review sample data before training
3. **Monitor Resources**: Large datasets need adequate RAM
4. **Compare Models**: Train multiple configurations to find best
5. **Save Metrics**: Record results for comparison over time

---

## ?? Useful Links

- **Blazor App**: `https://localhost:5001`
- **Python API Docs**: `http://localhost:8000/docs`
- **Python API Health**: `http://localhost:8000/health`
- **Architecture Docs**: See `ARCHITECTURE_ANALYSIS.md`
- **Integration Summary**: See `INTEGRATION_SUMMARY.md`

---

## ? Need Help?

### Check Logs
- **Blazor**: Open browser developer tools (F12) ? Console
- **Python**: Check terminal output where FastAPI is running

### Common Commands

```bash
# Restart Python service
Ctrl+C in terminal, then run: python -m uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Check if port 8000 is available
netstat -ano | findstr :8000

# Rebuild Blazor app
dotnet build

# Run Blazor in debug mode
dotnet run --configuration Debug
```

---

**Last Updated**: 2024  
**Status**: ? Ready for Use  
**Support**: Check ARCHITECTURE_ANALYSIS.md for detailed technical information
