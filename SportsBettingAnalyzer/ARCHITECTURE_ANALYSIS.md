# Python ML Service Architecture Analysis

## Current Architecture Overview

### Python Service Structure (mllearning/)
The Python repository contains a modern ML architecture with:

1. **Data Loading** (`src/data_loader.py`)
   - Loads sport-specific data from CSV files
   - Handles chronological train/test splits by season
   - Supports multiple sports with unified interface

2. **Sports Implementations** (`src/sports/`)
   - `base.py`: Abstract base class for all sports
   - `nfl.py`: NFL-specific logic (features, targets, preprocessing)
   - `nascar.py`: NASCAR-specific logic
   - `nba.py`: NBA support (placeholder)

3. **Model Pipeline** (`src/model_pipeline.py`)
   - Unified ML pipeline (preprocessing, feature engineering, modeling)
   - Supports both Classification and Regression tasks
   - Handles categorical/boolean/numeric features

4. **Training Module** (`src/train.py`)
   - `train_and_evaluate_sport()`: Trains model for any sport/task
   - Returns model path, metrics path, and evaluation metrics
   - Supports configurable train/test split seasons

5. **Prediction Module** (`src/predict.py`)
   - Loads trained models from joblib
   - Handles new data prediction with proper feature handling

6. **FastAPI Service** (`api/app.py`)
   - REST endpoints for training: `/sport/train/{task}`
 - REST endpoints for prediction: `/sport/predict/{task}`
   - Supports both Classification and Regression tasks
   - Model caching for performance

### Data Structure

**Available Data:**
```
mllearning/data/
??? nfl/raw/
?   ??? spreadspoke_scores.csv (NFL game scores)
?   ??? nfl_teams.csv (Team information)
??? nascar/raw/
?   ??? nascar race data.csv (Race results)
?   ??? cup_series.rda (R data archive)
?   ??? truck_series.rda (R data archive)
?   ??? xfinity_series.rda (R data archive)
??? nba/raw/
    ??? (placeholder for NBA data)
```

**Data Types Supported:**
- CSV files (primary format)
- RDA files (R data archives - need pyreadr package to parse)

### Supported Sports & Tasks

| Sport | Classification Task | Regression Task |
|-------|-------------------|-----------------|
| NFL | home_team_win (binary) | point_diff (continuous) |
| NASCAR | regression (finish position) | classification (top_finish) |
| NBA | (Not yet implemented) | (Not yet implemented) |

## New Vision: Blazor UI for Python ML Service

### Replacement of Old Architecture

**OLD (To Be Removed):**
- `KaggleNFLImportService` - External data importers
- `DataCollectionService` - Manual data scraping
- `MLModelService` - Legacy .NET ML.NET models
- `BetSlipOCRService` - OCR-based data collection

**NEW (Blazor UI Integration):**
- Direct integration with Python FastAPI service
- Use existing CSV/RDA datasets from `mllearning/data/`
- Unified training page for all sports
- Real-time model evaluation metrics

### Blazor Page Requirements

The new training page should:
1. **Display Available Datasets**
   - Show available sports (NFL, NASCAR, NBA)
   - Show dataset statistics (row count, date range)
   - List available features and targets

2. **Training Configuration**
   - Select sport
   - Select task (classification/regression)
   - Configure train/test split (by season)
   - Real-time data preview

3. **Training Execution**
   - Trigger FastAPI training endpoint
   - Display real-time progress
   - Show training metrics (accuracy, precision, recall, etc.)
- Display model metadata

4. **Model Management**
   - List trained models
   - Show model performance metrics
   - Delete old models
   - Export model information

5. **Prediction Interface** (Secondary)
   - Select trained model
   - Input features interactively
   - Display predictions
   - Show confidence scores

## Potential Issues & Solutions

### Issue 1: RDA File Support
**Problem:** RDA files are R format, need special parsing
**Solution:** 
- Use `pyreadr` package in Python
- Add RDA loading in `NFLSport` or new `NASCARSport` class
- Convert RDA to Pandas DataFrame

**Action:** Add to `src/sports/nascar.py`:
```python
import pyreadr

def load_rda_files(self):
  """Load NASCAR RDA files and merge with CSV data"""
    # Load RDA files
    cup = pyreadr.read_r(self.data_path / "cup_series.rda")
    # Convert to DataFrame
    df = cup['cup_series']  # Get dataframe from RDA
```

### Issue 2: FastAPI Service Availability
**Problem:** Python service needs to be running separately
**Solution:**
- Document setup requirements
- Create health check endpoint
- Implement graceful fallback if service unavailable
- Consider embedding Python service or using subprocess

**Action:** Add health check in Blazor:
```csharp
private async Task CheckPythonServiceHealth()
{
    try
    {
   var response = await _httpClient.GetAsync("http://localhost:8000/health");
        _isPythonServiceAvailable = response.IsSuccessStatusCode;
    }
    catch
    {
        _isPythonServiceAvailable = false;
    }
}
```

### Issue 3: Feature Column Handling
**Problem:** Different sports have different feature columns
**Solution:**
- Cache feature schemas per sport from `/sport/schema` endpoint
- Validate user input against schema
- Handle missing optional features gracefully

### Issue 4: Long-Running Training
**Problem:** Training could take minutes, HTTP timeout issues
**Solution:**
- Implement async polling with backoff
- Store training job status in database
- Return job ID for progress tracking
- WebSocket for real-time updates (optional)

### Issue 5: Data Format Consistency
**Problem:** CSV columns might have inconsistent naming/types
**Solution:**
- Already handled by `sport.preprocess_data()`
- Ensure consistency in data loading
- Add data validation endpoints

## Database Migrations Needed

Current: SQLite with `HistoricalGameResult`, `HistoricalBet` entities

**Proposed New Entities:**
```csharp
// Model metadata storage
public class TrainedModel
{
    public int Id { get; set; }
    public string Sport { get; set; } // "nfl", "nascar", "nba"
    public string Task { get; set; } // "classification", "regression"
    public string Series { get; set; } // "cup", "truck", null for NFL
    public DateTime TrainedAt { get; set; }
    public string ModelPath { get; set; }
    public string MetricsJson { get; set; }
    public decimal Accuracy { get; set; }
    public int NumTrainingSamples { get; set; }
}

// Training jobs
public class TrainingJob
{
    public int Id { get; set; }
    public string Sport { get; set; }
    public string Task { get; set; }
    public DateTime StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public string Status { get; set; } // "pending", "running", "complete", "error"
    public string? ErrorMessage { get; set; }
    public TrainedModelId TrainedModelId { get; set; }
}
```

## Recommended Implementation Order

1. **Phase 1: Core Integration**
   - Create `PythonMLService` wrapper for FastAPI calls
   - Add health check mechanism
   - Create database entities for model tracking

2. **Phase 2: Blazor UI**
   - Create `ModelTraining.razor` page
   - Dataset browser component
   - Training configuration component
   - Metrics display component

3. **Phase 3: Enhancement**
   - Real-time progress updates
   - Model management/deletion
   - Prediction interface
   - Historical training log

4. **Phase 4: Polish**
   - Error handling and user feedback
   - Async job management
   - Export functionality
   - API documentation

## Configuration Changes

**Update `appsettings.json`:**
```json
{
  "PythonMLService": {
    "BaseUrl": "http://localhost:8000",
    "Timeout": 300000,
    "HealthCheckInterval": 30000
  },
  "ModelStorage": {
    "Path": "C:\\Users\\dguil\\source\\repos\\PythonMLService\\mllearning\\data"
  }
}
```

**Update `Program.cs`:**
```csharp
builder.Services.AddScoped<PythonMLServiceClient>();
builder.Services.Configure<PythonMLOptions>(builder.Configuration.GetSection("PythonMLService"));
```
