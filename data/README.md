# Data Setup Guide

This directory contains the data files required to run the Sports ML Service. Due to size constraints, **large CSV files are NOT included in Git** and must be downloaded separately.

## Required Data Files

### NASCAR Data
- **Location**: `data/nascar/raw/`
- **Status**: Configured in `configs/nascar_config.yaml`
- **Download**: Via GitHub Actions or manual scripts (see below)

### NBA Data
These files are required for NBA model training:

| File | Size | Source | Download |
|------|------|--------|----------|
| `box_scores/PlayerStatistics.csv` | 303 MB | Kaggle | [Link](#download-instructions) |
| `box_scores/TeamStatistics.csv` | 32 MB | Kaggle | [Link](#download-instructions) |
| `box_scores/Games.csv` | 9.5 MB | Kaggle | [Link](#download-instructions) |
| `box_scores/Players.csv` | 0.5 MB | Kaggle | [Link](#download-instructions) |
| `box_scores/LeagueSchedule24_25.csv` | 0.14 MB | Kaggle | [Link](#download-instructions) |
| `box_scores/LeagueSchedule25_26.csv` | 0.17 MB | Kaggle | [Link](#download-instructions) |
| `box_scores/TeamHistories.csv` | Small | Kaggle | [Link](#download-instructions) |

**Total NBA Data**: ~346 MB

### NFL Data
- **File**: `team_stats/nfl_team_stats_2002-2024.csv`
- **Size**: 1.16 MB
- **Source**: Kaggle
- **Download**: [Link](#download-instructions)

## Download Instructions

### Option 1: Automatic Setup (Recommended)

Run the setup script from the repository root:

```bash
# Windows
python scripts/setup_data.py

# Or with explicit sport
python scripts/setup_data.py --sport nba
python scripts/setup_data.py --sport nfl
python scripts/setup_data.py --sport nascar
```

The script will:
- Check for required Kaggle API credentials
- Download datasets automatically
- Validate file integrity
- Organize files in correct directories
- Generate verification report

### Option 2: Manual Download from Kaggle

1. **Install Kaggle CLI**:
```bash
pip install kaggle
```

2. **Setup Kaggle API Credentials**:
   - Download your API token from https://www.kaggle.com/account
   - Place it at `~/.kaggle/kaggle.json` (Windows: `C:\Users\<username>\.kaggle\kaggle.json`)
   - Set permissions: `chmod 600 ~/.kaggle/kaggle.json` (Linux/Mac)

3. **Download NBA Data**:
```bash
# Create directory
mkdir -p data/nba/box_scores

# Download datasets (replace <dataset-name> with actual Kaggle dataset names)
kaggle datasets download -d <nba-stats-dataset> -p data/nba/box_scores --unzip
```

4. **Download NFL Data**:
```bash
mkdir -p data/nfl/team_stats
kaggle datasets download -d <nfl-stats-dataset> -p data/nfl/team_stats --unzip
```

5. **Verify Files**:
```bash
python scripts/verify_data.py
```

### Option 3: Use Existing Data

If you already have these CSV files locally:

```bash
# Copy files to correct locations
cp /path/to/PlayerStatistics.csv data/nba/box_scores/
cp /path/to/TeamStatistics.csv data/nba/box_scores/
cp /path/to/Games.csv data/nba/box_scores/
# ... etc

# Verify
python scripts/verify_data.py
```

## Data Validation

After downloading/placing files, validate them:

```bash
python scripts/verify_data.py
```

This script checks:
- ? File existence
- ? File size (within expected range)
- ? CSV integrity (can be parsed)
- ? Required columns present
- ? No corrupted data

## Directory Structure

Expected layout after setup:

```
data/
??? nba/
?   ??? box_scores/
?   ?   ??? PlayerStatistics.csv (303 MB)
?   ?   ??? TeamStatistics.csv (32 MB)
?   ?   ??? Games.csv (9.5 MB)
?   ?   ??? Players.csv (0.5 MB)
?   ?   ??? LeagueSchedule24_25.csv
?   ?   ??? LeagueSchedule25_26.csv
?   ?   ??? TeamHistories.csv
?   ??? (model outputs generated during training)
?
??? nfl/
?   ??? team_stats/
?   ?   ??? nfl_team_stats_2002-2024.csv (1.16 MB)
?   ??? (model outputs generated during training)
?
??? nascar/
    ??? raw/ (updated via GitHub Actions)
    ??? (model outputs generated during training)
```

## Troubleshooting

### Kaggle API Errors
```
Error: Kaggle API error - 401 - Invalid API key
```
**Solution**: Verify your Kaggle API token is correct and placed in the right location.

### File Not Found After Download
```
FileNotFoundError: PlayerStatistics.csv not found
```
**Solution**: Check that files were extracted from ZIP properly. Look in `Downloads/` directory.

### Insufficient Space
```
OSError: No space left on device
```
**Solution**: Ensure you have at least 400 MB free disk space.

### Corrupted CSV Files
```
ParsingError: Expected N fields in line X but got M
```
**Solution**: Re-download the file from Kaggle. Your download may have been interrupted.

## Size Management

?? **Note**: Large data files are intentionally excluded from Git to:
- Keep repository size manageable
- Prevent slow clones/pulls
- Respect GitHub's 100 MB file size limit
- Support different data versions

Use `.gitignore` rules to prevent accidental commits:
```
# In .gitignore
*.csv
data/nba/box_scores/
data/nfl/team_stats/
data/nascar/raw/
```

## Data Licensing

Ensure you comply with the licensing terms of each dataset:
- **Kaggle Datasets**: Subject to Kaggle's terms and individual dataset licenses
- **NASCAR Data**: Subject to applicable licensing agreements
- **NFL Data**: Verify licensing before commercial use

## Questions?

For issues with data download/setup:
1. Check the [troubleshooting guide](#troubleshooting) above
2. Review error messages from `python scripts/verify_data.py`
3. Check `setup_log.txt` generated by setup script
4. Open an issue on GitHub with:
   - Your OS (Windows/Linux/Mac)
   - Python version (`python --version`)
   - Error message (full traceback)
   - Size of your disk space available
