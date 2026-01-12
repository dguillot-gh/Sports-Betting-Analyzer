"""
NASCAR API Endpoints
Fetches live race data, schedules, and results from NASCAR's official API
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import httpx
import asyncio
import json
from datetime import datetime

router = APIRouter(prefix="/nascar", tags=["NASCAR"])

# NASCAR API base URLs
LIVE_FEED_URL = "https://cf.nascar.com/live/feeds/live-feed.json"
RACE_LIST_URL = "https://cf.nascar.com/cacher/{year}/race_list_basic.json"
WEEKEND_FEED_URL = "https://cf.nascar.com/cacher/{year}/{series}/{race_id}/weekend-feed.json"

# Cache for race data
_race_cache = {}
_cache_expiry = {}
CACHE_TTL = 3600  # 1 hour cache for schedule data


async def fetch_json(url: str, timeout: float = 10.0) -> dict:
    """Fetch JSON from URL with error handling"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=str(e))
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Failed to reach NASCAR API: {str(e)}")


@router.get("/live")
async def get_live_feed():
    """
    Get real-time race data from NASCAR live feed.
    Returns position updates, lap counts, flag status during races.
    When no race is active, returns race_id: -1
    """
    data = await fetch_json(LIVE_FEED_URL)
    
    # Transform vehicle data for easier consumption
    if data.get("vehicles"):
        vehicles = []
        for v in data["vehicles"]:
            vehicles.append({
                "position": v.get("running_position", 0),
                "carNumber": v.get("vehicle_number", ""),
                "driverName": f"{v.get('driver', {}).get('first_name', '')} {v.get('driver', {}).get('last_name', '')}".strip(),
                "lapsCompleted": v.get("laps_completed", 0),
                "delta": v.get("delta", 0),
                "lastLapTime": v.get("last_lap_time", 0),
                "status": v.get("status", "Running")
            })
        data["vehicles"] = vehicles
    
    return data


@router.get("/schedule/{year}")
async def get_schedule(
    year: int,
    series: int = Query(1, description="Series ID: 1=Cup, 2=Xfinity, 3=Trucks")
):
    """
    Get race schedule for a given year and series.
    Includes race names, dates, tracks, and results for completed races.
    """
    cache_key = f"{year}_{series}"
    
    # Check cache
    if cache_key in _race_cache and cache_key in _cache_expiry:
        if datetime.now().timestamp() < _cache_expiry[cache_key]:
            return _race_cache[cache_key]
    
    # Fetch from NASCAR
    url = RACE_LIST_URL.format(year=year)
    data = await fetch_json(url)
    
    # Get series data
    series_key = f"series_{series}"
    races = data.get(series_key, [])
    
    # Transform race data
    result = []
    for i, race in enumerate(races):
        result.append({
            "raceNumber": i + 1,
            "raceId": race.get("race_id", 0),
            "seriesId": race.get("series_id", series),
            "raceName": race.get("race_name", ""),
            "trackName": race.get("track_name", ""),
            "raceDate": race.get("race_date", ""),
            "scheduledLaps": race.get("scheduled_laps", 0),
            "actualLaps": race.get("actual_laps", 0),
            "stage1Laps": race.get("stage_1_laps", 0),
            "stage2Laps": race.get("stage_2_laps", 0),
            "stage3Laps": race.get("stage_3_laps", 0),
            "winnerDriverId": race.get("winner_driver_id", 0),
            "winnerName": "",  # Would need to lookup from driver data
            "numberOfCautions": race.get("number_of_cautions", 0),
            "numberOfCautionLaps": race.get("number_of_caution_laps", 0),
            "numberOfLeadChanges": race.get("number_of_lead_changes", 0),
            "numberOfLeaders": race.get("number_of_leaders", 0),
            "restrictorPlate": race.get("restrictor_plate", False),
            "marginOfVictory": race.get("margin_of_victory", ""),
            "averageSpeed": race.get("average_speed", 0)
        })
    
    # Cache result
    _race_cache[cache_key] = result
    _cache_expiry[cache_key] = datetime.now().timestamp() + CACHE_TTL
    
    return result


@router.get("/race/{race_id}")
async def get_race_details(race_id: int, year: int = 2026, series: int = 1):
    """
    Get detailed information for a specific race.
    Includes weekend schedule, qualifying, and race data.
    """
    url = WEEKEND_FEED_URL.format(year=year, series=series, race_id=race_id)
    return await fetch_json(url)


@router.get("/status")
async def get_status():
    """
    Check if NASCAR API is accessible and if a race is currently live.
    """
    try:
        live_data = await fetch_json(LIVE_FEED_URL)
        is_live = live_data.get("race_id", -1) > 0
        
        return {
            "api_available": True,
            "race_live": is_live,
            "race_id": live_data.get("race_id", -1),
            "track_name": live_data.get("track_name", ""),
            "lap": live_data.get("lap_number", 0),
            "flag_state": live_data.get("flag_state", 0)
        }
    except Exception as e:
        return {
            "api_available": False,
            "error": str(e)
        }


# ============================================
# LIVE DATA CAPTURE - Store historical snapshots
# ============================================

import os
from pathlib import Path
import asyncio

# Data storage path
DATA_DIR = Path(__file__).parent.parent / "data" / "nascar" / "live_captures"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Active capture state
_capture_active = False
_capture_task = None
_capture_interval = 5  # seconds between captures


@router.post("/capture/start")
async def start_capture(interval: int = Query(5, description="Capture interval in seconds")):
    """
    Start capturing live feed data during a race.
    Stores snapshots every N seconds with lap-by-lap position data.
    Works for ALL series (Cup, Xfinity, Trucks) - series_id in response identifies which.
    """
    global _capture_active, _capture_interval, _capture_task
    
    if _capture_active:
        return {"status": "already_running", "interval": _capture_interval}
    
    _capture_interval = max(1, min(60, interval))  # Clamp 1-60 seconds
    _capture_active = True
    
    # Start background capture
    _capture_task = asyncio.create_task(_capture_loop())
    
    return {
        "status": "started",
        "interval": _capture_interval,
        "note": "Captures ALL series - Cup/Xfinity/Trucks identified by series_id"
    }


@router.post("/capture/stop")
async def stop_capture():
    """Stop the live feed capture."""
    global _capture_active, _capture_task
    
    _capture_active = False
    if _capture_task:
        _capture_task.cancel()
        _capture_task = None
    
    return {"status": "stopped"}


@router.get("/capture/status")
async def get_capture_status():
    """Get current capture status and stored data summary."""
    files = list(DATA_DIR.glob("*.json"))
    
    # Group by race
    races = {}
    for f in files:
        parts = f.stem.split("_")
        if len(parts) >= 3:
            race_key = f"{parts[0]}_{parts[1]}"  # series_raceId
            if race_key not in races:
                races[race_key] = {"snapshots": 0, "first": None, "last": None}
            races[race_key]["snapshots"] += 1
    
    return {
        "capture_active": _capture_active,
        "interval": _capture_interval,
        "total_snapshots": len(files),
        "races_captured": len(races),
        "storage_path": str(DATA_DIR)
    }


@router.get("/capture/data/{race_id}")
async def get_captured_data(
    race_id: int,
    series: int = Query(1, description="Series ID")
):
    """
    Get all captured snapshots for a specific race.
    Returns lap-by-lap position history.
    """
    pattern = f"{series}_{race_id}_*.json"
    files = sorted(DATA_DIR.glob(pattern))
    
    if not files:
        return {"error": "No data captured for this race", "race_id": race_id}
    
    snapshots = []
    for f in files:
        try:
            with open(f) as fp:
                snapshots.append(json.load(fp))
        except:
            continue
    
    return {
        "race_id": race_id,
        "series_id": series,
        "snapshot_count": len(snapshots),
        "snapshots": snapshots
    }


@router.get("/capture/position-history/{race_id}")
async def get_position_history(
    race_id: int,
    series: int = Query(1, description="Series ID"),
    driver: Optional[str] = Query(None, description="Filter by driver name (partial match)")
):
    """
    Get position history for drivers through the race.
    Perfect for analyzing position changes over time.
    """
    pattern = f"{series}_{race_id}_*.json"
    files = sorted(DATA_DIR.glob(pattern))
    
    if not files:
        return {"error": "No data captured for this race"}
    
    # Build position history by lap
    history = {}  # driver_name -> list of {lap, position}
    
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
                lap = data.get("lap_number", 0)
                for v in data.get("vehicles", []):
                    name = v.get("driverName", "")
                    if driver and driver.lower() not in name.lower():
                        continue
                    if name not in history:
                        history[name] = []
                    history[name].append({
                        "lap": lap,
                        "position": v.get("position", 0),
                        "delta": v.get("delta", 0)
                    })
        except:
            continue
    
    return {
        "race_id": race_id,
        "drivers": len(history),
        "history": history
    }


async def _capture_loop():
    """Background task to capture live feed data."""
    global _capture_active
    
    while _capture_active:
        try:
            data = await fetch_json(LIVE_FEED_URL)
            race_id = data.get("race_id", -1)
            series_id = data.get("series_id", 0)
            lap = data.get("lap_number", 0)
            
            if race_id > 0:  # Only save if race is active
                # Transform vehicles
                if data.get("vehicles"):
                    vehicles = []
                    for v in data["vehicles"]:
                        vehicles.append({
                            "position": v.get("running_position", 0),
                            "carNumber": v.get("vehicle_number", ""),
                            "driverName": f"{v.get('driver', {}).get('first_name', '')} {v.get('driver', {}).get('last_name', '')}".strip(),
                            "lapsCompleted": v.get("laps_completed", 0),
                            "delta": v.get("delta", 0),
                            "lastLapTime": v.get("last_lap_time", 0),
                            "status": v.get("status", "Running")
                        })
                    data["vehicles"] = vehicles
                
                # Save snapshot
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{series_id}_{race_id}_{lap:04d}_{timestamp}.json"
                filepath = DATA_DIR / filename
                
                with open(filepath, "w") as f:
                    json.dump(data, f, indent=2)
                
        except Exception as e:
            print(f"Capture error: {e}")
        
        await asyncio.sleep(_capture_interval)


# ============================================
# ML DATA CONSOLIDATION - Convert to Parquet
# ============================================

import pandas as pd

# ML-ready data storage
ML_DATA_DIR = Path(__file__).parent.parent / "data" / "nascar" / "ml_datasets"
ML_DATA_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/ml/consolidate/{race_id}")
async def consolidate_to_parquet(
    race_id: int,
    series: int = Query(1, description="Series ID"),
    cleanup: bool = Query(False, description="Delete JSON files after consolidation")
):
    """
    Consolidate JSON snapshots into ML-ready Parquet file.
    Creates structured dataset with:
    - Position history per driver
    - Lap times and deltas
    - Computed features for ML analysis
    """
    pattern = f"{series}_{race_id}_*.json"
    files = sorted(DATA_DIR.glob(pattern))
    
    if not files:
        raise HTTPException(404, f"No captured data for race {race_id}")
    
    # Collect all position data
    rows = []
    race_info = None
    
    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
                
                if race_info is None:
                    race_info = {
                        "race_id": data.get("race_id"),
                        "series_id": data.get("series_id"),
                        "track_name": data.get("track_name"),
                        "laps_in_race": data.get("laps_in_race")
                    }
                
                lap = data.get("lap_number", 0)
                flag_state = data.get("flag_state", 0)
                timestamp = data.get("time_of_day_os", "")
                
                for v in data.get("vehicles", []):
                    rows.append({
                        "lap": lap,
                        "flag_state": flag_state,
                        "timestamp": timestamp,
                        "driver_name": v.get("driverName", ""),
                        "car_number": v.get("carNumber", ""),
                        "position": v.get("position", 0),
                        "laps_completed": v.get("lapsCompleted", 0),
                        "delta": v.get("delta", 0.0),
                        "last_lap_time": v.get("lastLapTime", 0.0),
                        "status": v.get("status", "Running")
                    })
        except Exception as e:
            print(f"Error reading {f}: {e}")
            continue
    
    if not rows:
        raise HTTPException(400, "No valid data found in snapshots")
    
    # Create DataFrame
    df = pd.DataFrame(rows)
    
    # Add computed features for ML
    df["is_caution"] = df["flag_state"] == 2
    df["is_running"] = df["status"] == "Running"
    
    # Position change per lap (per driver)
    df = df.sort_values(["driver_name", "lap"])
    df["position_change"] = df.groupby("driver_name")["position"].diff().fillna(0)
    df["positions_gained"] = -df["position_change"]  # Negative = gained positions
    
    # Lap time improvements
    df["lap_time_change"] = df.groupby("driver_name")["last_lap_time"].diff().fillna(0)
    
    # Rolling averages (5-lap window)
    df["avg_position_5lap"] = df.groupby("driver_name")["position"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )
    df["avg_lap_time_5lap"] = df.groupby("driver_name")["last_lap_time"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )
    
    # Save to Parquet
    output_file = ML_DATA_DIR / f"race_{series}_{race_id}_positions.parquet"
    df.to_parquet(output_file, index=False)
    
    # Create race summary
    summary_data = {
        **race_info,
        "total_laps_captured": df["lap"].nunique(),
        "drivers_tracked": df["driver_name"].nunique(),
        "total_records": len(df),
        "caution_laps": df[df["is_caution"]]["lap"].nunique(),
        "avg_positions_gained": df["positions_gained"].mean()
    }
    
    summary_file = ML_DATA_DIR / f"race_{series}_{race_id}_summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary_data, f, indent=2)
    
    # Cleanup JSON files if requested
    if cleanup:
        for f in files:
            f.unlink()
    
    return {
        "status": "success",
        "parquet_file": str(output_file),
        "summary_file": str(summary_file),
        "records": len(df),
        "drivers": df["driver_name"].nunique(),
        "laps": df["lap"].nunique(),
        "file_size_mb": round(output_file.stat().st_size / 1024 / 1024, 2),
        "features": list(df.columns)
    }


@router.get("/ml/datasets")
async def list_ml_datasets():
    """List all available ML datasets (consolidated Parquet files)."""
    parquet_files = list(ML_DATA_DIR.glob("*.parquet"))
    
    datasets = []
    for f in parquet_files:
        try:
            # Parse filename: race_{series}_{race_id}_positions.parquet
            parts = f.stem.split("_")
            series_id = int(parts[1]) if len(parts) > 1 else 0
            race_id = int(parts[2]) if len(parts) > 2 else 0
            
            # Get summary if exists
            summary_file = f.parent / f"race_{series_id}_{race_id}_summary.json"
            summary = {}
            if summary_file.exists():
                with open(summary_file) as fp:
                    summary = json.load(fp)
            
            datasets.append({
                "file": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
                "series_id": series_id,
                "race_id": race_id,
                "track_name": summary.get("track_name", "Unknown"),
                "laps": summary.get("total_laps_captured", 0),
                "drivers": summary.get("drivers_tracked", 0)
            })
        except Exception as e:
            datasets.append({"file": f.name, "error": str(e)})
    
    return {
        "total_datasets": len(datasets),
        "storage_path": str(ML_DATA_DIR),
        "datasets": datasets
    }


@router.get("/ml/dataset/{race_id}")
async def get_ml_dataset(
    race_id: int,
    series: int = Query(1, description="Series ID"),
    driver: Optional[str] = Query(None, description="Filter by driver name"),
    sample: int = Query(100, description="Number of rows to return (0 = all)")
):
    """
    Get ML dataset for a specific race.
    Returns position history with computed features.
    """
    file_path = ML_DATA_DIR / f"race_{series}_{race_id}_positions.parquet"
    
    if not file_path.exists():
        raise HTTPException(404, f"No ML dataset for race {race_id}. Run /ml/consolidate first.")
    
    df = pd.read_parquet(file_path)
    
    # Apply filters
    if driver:
        df = df[df["driver_name"].str.contains(driver, case=False, na=False)]
    
    # Sample or limit
    if sample > 0 and len(df) > sample:
        df = df.sample(sample)
    
    return {
        "race_id": race_id,
        "series_id": series,
        "total_records": len(df),
        "columns": list(df.columns),
        "data": df.to_dict(orient="records")
    }


@router.get("/ml/driver-stats/{race_id}")
async def get_driver_race_stats(
    race_id: int,
    series: int = Query(1, description="Series ID")
):
    """
    Get aggregated driver stats from a race for ML modeling.
    Perfect for training race prediction models.
    """
    file_path = ML_DATA_DIR / f"race_{series}_{race_id}_positions.parquet"
    
    if not file_path.exists():
        raise HTTPException(404, f"No ML dataset for race {race_id}")
    
    df = pd.read_parquet(file_path)
    
    # Aggregate stats per driver
    stats = df.groupby(["driver_name", "car_number"]).agg({
        "position": ["min", "max", "mean", "std", "last"],
        "positions_gained": "sum",
        "last_lap_time": ["min", "mean", "std"],
        "laps_completed": "max",
        "is_running": "last"
    }).reset_index()
    
    # Flatten column names
    stats.columns = [
        "driver_name", "car_number",
        "best_position", "worst_position", "avg_position", "position_std", "finish_position",
        "total_positions_gained", 
        "best_lap_time", "avg_lap_time", "lap_time_std",
        "laps_completed", "finished_running"
    ]
    
    # Rank by finish position
    stats = stats.sort_values("finish_position")
    stats["finish_rank"] = range(1, len(stats) + 1)
    
    return {
        "race_id": race_id,
        "series_id": series,
        "drivers": len(stats),
        "stats": stats.to_dict(orient="records")
    }


# ============================================
# LIVE ODDS - AI Predictions
# ============================================

from scripts.nascar_ai_integration import get_nascar_ai_predictions
from src.sports.nascar import NASCARSport
from services.nascar_odds_service import NascarOddsService

# Initialize odds service
_odds_service = NascarOddsService()

@router.get("/predictions/{race_id}")
async def get_race_predictions(race_id: int):
    """
    Get live AI predictions for ALL drivers in a race.
    Returns: Sorted list of drivers by Win Probability.
    Now includes Market Odds from The Odds API.
    """
    try:
        # 1. Fetch Race Details to get Track Name
        details = await get_race_details(race_id, year=2026)
        track_name = details.get("track_name", "Unknown Track")
        
        # 2. Get Roster (Active drivers for 2026)
        sport = NASCARSport()
        roster = sport.get_roster(year=2026)
        
        # 3. Prefetch Market Odds (Optimization)
        # We fetch all odds once, then lookup per driver
        await _odds_service.get_live_odds()
        
        # 4. Generate Predictions & Merge Odds
        predictions = []
        for driver in roster:
            name = driver.get("driver", "Unknown")
            stats = sport.get_entity_stats(name)
            
            # Predict
            pred = get_nascar_ai_predictions(
                driver_name=name,
                track_name=track_name,
                driver_stats=stats,
                track_type="Intermediate"  # Ideally lookup from track metadata
            )
            
            # Extract key metrics
            engines = pred.get("engines", {})
            ml_model = engines.get("XGBoostClassifier", {})
            fallback = engines.get("TrackBaseline", {})
            
            # Prefer model, fallback to baseline
            win_prob = ml_model.get("win_prob") or fallback.get("win_prob", 0.0)
            proj_finish = engines.get("XGBoostRegressor", {}).get("predicted_finish") or fallback.get("predicted_finish", 20.0)
            
            # Lookup Market Odds
            market_odds = await _odds_service.get_driver_odds(name)
            
            predictions.append({
                "driver_name": name,
                "car_number": driver.get("number", "00"),
                "win_probability": win_prob,
                "projected_finish": proj_finish,
                "market_odds": market_odds or "N/A",  # New Field
                "engines": engines,
                "confidence": ml_model.get("confidence", "Low")
            })
            
        # 5. Sort by Win Probability (Desc)
        predictions.sort(key=lambda x: x["win_probability"], reverse=True)
        
        # Assign ranks
        for i, p in enumerate(predictions):
            p["rank"] = i + 1
            
        return {
            "race_id": race_id,
            "track_name": track_name,
            "prediction_count": len(predictions),
            "predictions": predictions
        }
        
    except Exception as e:
        print(f"Prediction error: {e}")
        return {"error": str(e)}
