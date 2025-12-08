# Sports ML Service - Machine Learning API

A FastAPI-based machine learning service for predicting sports outcomes. Provides APIs for training models, making predictions, and analyzing player/team statistics across multiple sports (NASCAR, NFL, NBA).

## ?? Quick Start

### Prerequisites
- Python 3.9+
- pip/conda
- ~400 MB disk space for datasets
- Kaggle account (for downloading data)

### Installation

```bash
# Clone repository
git clone https://github.com/dguillot-gh/mllearning.git
cd mllearning

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup data (download datasets)
python scripts/setup_data.py

# Start the service
python -m uvicorn api.app:app --reload --port 8000
```

The API will be available at `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Swagger UI: `http://localhost:8000/redoc`

## ?? Data Setup

Large CSV datasets are NOT included in Git (to keep repository size manageable). You need to download them before running the service.

### Automatic Setup (Recommended)

```bash
# Download all datasets
python scripts/setup_data.py

# Or specific sport
python scripts/setup_data.py --sport nba

# Only verify existing files
python scripts/setup_data.py --verify-only
```

### Data Files Required

| Sport | File | Size | Status |
|-------|------|------|--------|
| **NBA** | `data/nba/box_scores/PlayerStatistics.csv` | 303 MB | Required |
| | `data/nba/box_scores/TeamStatistics.csv` | 32 MB | Required |
| | `data/nba/box_scores/Games.csv` | 9.5 MB | Required |
| **NFL** | `data/nfl/team_stats/nfl_team_stats_2002-2024.csv` | 1.16 MB | Required |
| **NASCAR** | `data/nascar/raw/*` | Various | Auto-updated |

### Manual Setup

See detailed instructions in [`data/README.md`](data/README.md)

## ?? Project Structure

```
mllearning/
??? api/          # FastAPI application
?   ??? app.py        # Main API endpoints
??? src/         # Core ML modules
?   ??? train.py            # Model training
?   ??? model_pipeline.py   # ML pipeline
?   ??? sports/    # Sport-specific modules
?   ?   ??? nascar.py
?   ?   ??? nfl.py
?   ?   ??? nba.py
? ??? data_loader.py     # Data loading utilities
??? data/     # Datasets (NOT in Git)
?   ??? nba/
?   ??? nfl/
?   ??? nascar/
??? models/           # Trained models (joblib files)
?   ??? nba/
?   ??? nfl/
?   ??? nascar/
??? configs/        # Configuration files
?   ??? nascar_config.yaml
??? scripts/     # Utility scripts
?   ??? setup_data.py       # Download datasets
?   ??? verify_data.py # Validate datasets
??? requirements.txt    # Python dependencies
```

## ?? API Endpoints

### Health Check
```
GET /health
```
Returns service status and available sports.

### Data Management
```
# Get data schema
GET /{sport}/schema

# Get available data
GET /{sport}/data?limit=1000&skip=0

# Get data status for all sports
GET /data/status

# Update data from external sources
POST /data/update/{sport}

# Check for dataset updates
POST /data/check-updates/{sport}

# Get update history
GET /data/history/{sport}
```

### Model Training
```
# Train a new model
POST /{sport}/train/{task}

# Get trained models
GET /{sport}/models

# Delete a model
DELETE /{sport}/models/{series}/{task}

# Retrain models
POST /data/retrain/{sport}
```

### Predictions
```
# Make single prediction
POST /{sport}/predict/{task}

# Batch predictions from CSV
POST /{sport}/predict/batch/{task}

# Run simulation
POST /{sport}/simulate
```

### Entity Information
```
# Get all entities (drivers/teams)
GET /{sport}/entities

# Get entity profile/stats
GET /{sport}/profile/{entity_id}

# Get drivers
GET /{sport}/drivers

# Get teams
GET /{sport}/teams

# Get roster
GET /{sport}/roster/{series}

# Upcoming races
GET /{sport}/upcoming
```

### Features
```
# Get feature values
GET /{sport}/features/values
```

## ?? Configuration

### Environment Variables
```bash
# Python ML Service configuration
PYTHON_ML_BASE_URL=http://localhost:8000
PYTHON_ML_TIMEOUT=300
PYTHON_ML_HEALTH_CHECK_INTERVAL=30
```

### Dataset Configuration
See `configs/nascar_config.yaml` for sport-specific configurations.

## ?? Training Models

### Basic Training

```python
import requests

# Train a classification model
response = requests.post(
    "http://localhost:8000/nba/train/classification",
    json={
        "task": "classification",
    "test_start_season": 2023,
 "train_start_season": 2015
    }
)
print(response.json())
```

### Multi-Target Training (NASCAR)

```python
# Train multiple targets for NASCAR
response = requests.post(
    "http://localhost:8000/nascar/train/classification",
    json={
        "task": "classification",
 "series": "cup",
        "hyperparameters": {
        "n_estimators": 100,
"max_depth": 10
        }
}
)
```

## ?? Data Validation

Verify all datasets before training:

```bash
# Validate all data
python scripts/verify_data.py

# Generate detailed report
python scripts/verify_data.py --report

# Validate specific sport
python scripts/verify_data.py --sport nba
```

The validator checks:
- ? File existence
- ? File size
- ? CSV format validity
- ? Required columns
- ? Row counts
- ? Null value ratios

## ?? Troubleshooting

### Service Not Starting

```
error: Module not found
```
**Solution**: Install dependencies:
```bash
pip install -r requirements.txt
```

### Missing Data Files
```
FileNotFoundError: PlayerStatistics.csv not found
```
**Solution**: Download data:
```bash
python scripts/setup_data.py
```

### Kaggle API Errors
```
Error: Kaggle API credentials not found
```
**Solution**: Setup Kaggle credentials:
1. Go to https://www.kaggle.com/account
2. Click "Create New Token"
3. Place `kaggle.json` in `~/.kaggle/`
4. Run `python scripts/setup_data.py`

### CSV Parsing Errors
```
ParsingError: Expected N fields in line X but got M
```
**Solution**: Re-download the file (may have been corrupted):
```bash
python scripts/setup_data.py --sport nba
```

## ?? Documentation

- **Data Setup**: See [`data/README.md`](data/README.md)
- **API Reference**: Visit `http://localhost:8000/docs` when service is running
- **Configuration**: See `configs/nascar_config.yaml`

## ?? Data Management

### Automatic Updates
NASCAR data is automatically updated via GitHub Actions. Check the latest in `data/nascar/raw/`.

### Manual Updates
```bash
# Update specific sport
curl -X POST http://localhost:8000/data/update/nba

# Check for updates
curl -X POST http://localhost:8000/data/check-updates/nfl

# View history
curl http://localhost:8000/data/history/nascar
```

## ?? Integration with .NET

The `SportsBettingAnalyzer` .NET Blazor application integrates with this service via HTTP:

```csharp
var client = new PythonMLServiceClient(httpClient, options, logger);

// Get model info
var models = await client.GetModelsAsync("nba");

// Make prediction
var prediction = await client.PredictAsync(
    sport: "nba",
    task: "classification",
    request: new PredictRequest { Features = featureDict }
);

// Train a model
var result = await client.TrainAsync(
    sport: "nascar",
    task: "classification",
    series: "cup"
);
```

See `../SportsBettingAnalyzer/Services/PythonMLServiceClient.cs` for full integration details.

## ?? Model Metrics

After training, metrics are saved as JSON:
```
models/{sport}/{series}/{task}_metrics.json
```

Example:
```json
{
  "accuracy": 0.875,
  "precision": 0.92,
  "recall": 0.81,
  "f1_score": 0.86,
  "training_time": 120.5
}
```

## ?? Supported Models

- **Classification**: Random Forest, Gradient Boosting
- **Regression**: Linear Regression, Random Forest
- **Simulation**: Monte Carlo for race outcome prediction

## ?? Performance

- Model training: 30 seconds - 5 minutes (depends on data size)
- Single prediction: < 100 ms
- Batch predictions: ~1-2 ms per record
- Simulation (1000 iterations): 5-10 seconds

## ?? Logging

Logs are output to console and optionally to file:
```
INFO - Server started on port 8000
INFO - Loading NASCAR data...
INFO - Training classification model...
```

Set log level:
```bash
# Debug level
export LOG_LEVEL=DEBUG
python -m uvicorn api.app:app --log-level debug
```

## ?? Security

?? **Note**: This service is designed for development/testing. For production:
- Enable CORS restrictions
- Add authentication
- Use environment variables for secrets
- Run behind reverse proxy (nginx/Apache)
- Enable HTTPS

## ?? License

See LICENSE file for details.

## ?? Contributing

1. Create feature branch
2. Make changes
3. Test with `python scripts/verify_data.py`
4. Commit with clear message
5. Push and create PR

## ?? Support

For issues or questions:
1. Check documentation in `data/README.md`
2. Review API docs at `/docs`
3. Check logs for error messages
4. Open GitHub issue with:
- OS (Windows/Linux/Mac)
   - Python version
   - Error message (full traceback)
   - Steps to reproduce

---

**Last Updated**: 2025-01-14
**Version**: 1.2
**Python**: 3.9+
**Status**: ? Production Ready
