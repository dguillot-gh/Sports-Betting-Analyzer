"""
NASCAR Supplemental Importer
─────────────────────────────
Combines two sources to fill gaps when the kylegrealis parquet is stale:

  1. DriverAverages.com (HTML scrape)  — base data for ALL completed races
     Fields: Fin, St, #, Driver, Make, Pts, Laps, Led, Status, Team, S1, S2, Rating
     Matches parquet format ~95%.

  2. NASCAR.com Live Feed (JSON)       — enrichment for the LATEST race only
     Extras: avg_speed, best_lap_speed, best_lap_time, passes_made,
             passing_differential, pit_stops, quality_passes, laps_position_improved

The importer:
  • Scrapes DriverAverages for each completed race in the current season
  • Merges live-feed extras into the latest race by matching driver name
  • Produces metadata identical to the parquet importer (dual raw + standardized keys)
  • Uses the same content_hash so records merge cleanly with parquet data

Can be called from the scheduler or run standalone.
"""

import asyncio
import json
import hashlib
import logging
import os
import re
from datetime import datetime

import asyncpg
import requests
from bs4 import BeautifulSoup

from src.config import DATABASE_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# DriverAverages.com — series-specific URL paths
DA_SERIES_PATHS = {
    "cup":     "nascar_stats",
    "xfinity": "nascar_xfinityseries",
    "trucks":  "nascar_truckseries",
}
DA_SEASON_URL = "https://www.driveraverages.com/{da_path}/year.php?yr_id={year}"
DA_RACE_URL = "https://www.driveraverages.com/{da_path}/race.php?sked_id={sked_id}"

# NASCAR.com feed URLs
NASCAR_LIVE_FEED = "https://cf.nascar.com/live/feeds/live-feed.json"
NASCAR_XFINITY_LIVE_FEED = "https://cf.nascar.com/live/feeds/series_2/live-feed.json"
NASCAR_TRUCKS_LIVE_FEED = "https://cf.nascar.com/live/feeds/series_3/live-feed.json"
NASCAR_SCHEDULE_URL = "https://cf.nascar.com/cacher/{year}/{series_id}/race_list_basic.json"

# Series mapping
SERIES_MAP = {
    1: "cup",
    2: "xfinity",
    3: "trucks",
}

# ─── Utilities ────────────────────────────────────────────────────────────────

def compute_hash(data: dict) -> str:
    """Same hash as parquet importer for dedup."""
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def safe_int(val):
    """Convert a string/float to int safely."""
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return None


def safe_float(val):
    """Convert a string to float safely."""
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def normalize_driver(name: str) -> str:
    """Normalize driver name for matching between sources."""
    name = re.sub(r'\s*[#(].*', '', name)  # Remove (#88), (i), etc.
    name = re.sub(r'^\*\s*', '', name)     # Remove leading asterisk (*)
    name = name.strip()
    return name


# ─── Source 1: DriverAverages.com ─────────────────────────────────────────────

def get_da_race_list(year: int, series: str = "cup") -> list[dict]:
    """Scrape the season page to get a list of completed race sked_ids."""
    da_path = DA_SERIES_PATHS.get(series, DA_SERIES_PATHS["cup"])
    url = DA_SEASON_URL.format(da_path=da_path, year=year)
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        if r.status_code != 200:
            logger.warning(f"DriverAverages season page returned {r.status_code}")
            return []
    except Exception as e:
        logger.error(f"Failed to fetch DA season page: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    races = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "sked_id=" in href:
            sked_id = href.split("sked_id=")[-1].split("&")[0]
            label = a.get_text(strip=True)
            # Extract track name from label like "Feb 15 - Daytona"
            parts = label.split(" - ", 1)
            track = parts[1].strip() if len(parts) > 1 else label
            races.append({
                "sked_id": sked_id,
                "label": label,
                "track": track,
            })

    logger.info(f"DriverAverages: found {len(races)} completed races for {year}")
    return races


def scrape_da_race_results(sked_id: str, series: str = "cup") -> list[dict] | None:
    """Scrape full race results from a DriverAverages race page.
    Returns list of dicts with parquet-compatible field names."""
    da_path = DA_SERIES_PATHS.get(series, DA_SERIES_PATHS["cup"])
    url = DA_RACE_URL.format(da_path=da_path, sked_id=sked_id)
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        if r.status_code != 200:
            logger.warning(f"DA race {sked_id}: HTTP {r.status_code}")
            return None
    except Exception as e:
        logger.error(f"DA race {sked_id} fetch error: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Find the results table — look for headers: Fin, St, #, Driver, Make, ...
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 5:
            continue

        # Prefer header rows with <th> tags (the real results table uses all <th>)
        header_cells = rows[0].find_all("th")
        if len(header_cells) < 4:
            # Fallback to mixed th/td if no pure-th header
            header_cells = rows[0].find_all(["th", "td"])
            if len(header_cells) < 4:
                continue

        headers = [c.get_text(strip=True) for c in header_cells]
        header_lower = [h.lower() for h in headers]

        # Must have BOTH a finish column AND a driver column to be the results table
        has_fin = any(h in header_lower for h in ("fin", "finish"))
        has_driver = "driver" in header_lower
        if not has_fin or not has_driver:
            continue
        
        logger.debug(f"DA table candidate: {len(rows)-1} rows, headers={headers}")

        # Build column index map
        col_map = {}
        for i, h in enumerate(header_lower):
            if h in ("fin", "finish"):
                col_map["Finish"] = i
            elif h in ("st", "start"):
                col_map["Start"] = i
            elif h == "#":
                col_map["Number"] = i
            elif h == "driver":
                col_map["Driver"] = i
            elif h in ("make", "mfg", "manufacturer"):
                col_map["Manufacturer"] = i
            elif h in ("pts", "points"):
                col_map["Pts"] = i
            elif h == "laps":
                col_map["Laps"] = i
            elif h == "led":
                col_map["Led"] = i
            elif h == "status":
                col_map["Status"] = i
            elif h == "team":
                col_map["Team"] = i
            elif h == "s1":
                col_map["Stage1"] = i
            elif h == "s2":
                col_map["Stage2"] = i
            elif h in ("rating", "rtg"):
                col_map["Rating"] = i

        results = []
        for row in rows[1:]:
            cells = row.find_all("td")
            vals = [c.get_text(strip=True) for c in cells]
            if len(vals) < 4:
                continue

            def cell(key):
                idx = col_map.get(key)
                if idx is not None and idx < len(vals):
                    return vals[idx]
                return None

            driver_raw = cell("Driver") or "Unknown"
            driver = normalize_driver(driver_raw)

            # Skip manufacturer summary rows (e.g. "Toyota", "Ford", "Chevrolet")
            if driver.lower() in ("toyota", "ford", "chevrolet", "dodge", "honda", "unknown", ""):
                continue

            entry = {
                "Driver": driver,
                "Finish": safe_int(cell("Finish")),
                "Start": safe_int(cell("Start")),
                "Manufacturer": cell("Manufacturer"),
                "Pts": safe_int(cell("Pts")),
                "Laps": safe_int(cell("Laps")),
                "Led": safe_int(cell("Led")),
                "Status": cell("Status") or "running",
                "Team": cell("Team"),
                "Rating": safe_float(cell("Rating")),
                "Number": cell("Number"),
                "Stage1": safe_int(cell("Stage1")),
                "Stage2": safe_int(cell("Stage2")),
            }

            # Remove None values
            entry = {k: v for k, v in entry.items() if v is not None}
            results.append(entry)

        if len(results) >= 10:
            logger.info(f"DA race {sked_id}: scraped {len(results)} drivers")
            return results
        elif results:
            logger.warning(f"DA race {sked_id}: only {len(results)} rows — likely not full results, skipping")

    logger.warning(f"DA race {sked_id}: no results table found")
    return None


# ─── Source 2: NASCAR.com Live Feed ───────────────────────────────────────────

def fetch_live_feed(series: str = "cup") -> dict | None:
    """Fetch the NASCAR.com live feed for a series. Returns parsed data or None."""
    url_map = {
        "cup": NASCAR_LIVE_FEED,
        "xfinity": NASCAR_XFINITY_LIVE_FEED,
        "trucks": NASCAR_TRUCKS_LIVE_FEED,
    }
    url = url_map.get(series, NASCAR_LIVE_FEED)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        # Only return if race is finished (flag_state 9 = checkered)
        if data.get("flag_state") != 9:
            logger.info(f"Live feed {series}: flag_state={data.get('flag_state')}, not finished")
            return None
        return data
    except Exception as e:
        logger.error(f"Live feed {series} error: {e}")
        return None


def parse_live_feed(data: dict) -> tuple[dict, list[dict]]:
    """Parse the live feed into race info + list of driver result dicts."""
    race_info = {
        "race_id": data.get("race_id"),
        "track": data.get("track_name", "Unknown"),
        "laps_in_race": data.get("laps_in_race"),
        "series_id": data.get("series_id"),
    }

    vehicles = data.get("vehicles", [])
    results = []
    for v in sorted(vehicles, key=lambda x: x.get("running_position", 999)):
        driver_info = v.get("driver", {})
        driver_name = driver_info.get("full_name", "Unknown")

        # Calculate total laps led from segment list
        led_segments = v.get("laps_led", [])
        total_led = 0
        if isinstance(led_segments, list):
            for seg in led_segments:
                if isinstance(seg, dict):
                    total_led += seg.get("end_lap", 0) - seg.get("start_lap", 0) + 1

        entry = {
            "Driver": normalize_driver(driver_name),
            "Finish": v.get("running_position"),
            "Start": v.get("starting_position"),
            "Laps": v.get("laps_completed"),
            "Led": total_led,
            "Manufacturer": v.get("vehicle_manufacturer"),
            "Number": v.get("vehicle_number"),
            # Extras only from live feed
            "avg_speed": safe_float(v.get("average_speed")),
            "best_lap_speed": safe_float(v.get("best_lap_speed")),
            "best_lap_time": safe_float(v.get("best_lap_time")),
            "avg_restart_speed": safe_float(v.get("average_restart_speed")),
            "passes_made": safe_int(v.get("passes_made")),
            "quality_passes": safe_int(v.get("quality_passes")),
            "passing_diff": safe_int(v.get("passing_differential")),
            "laps_pos_improved": safe_int(v.get("laps_position_improved")),
            "fastest_laps_run": safe_int(v.get("fastest_laps_run")),
            "driver_id": driver_info.get("driver_id"),
        }

        # Pit stop count
        pit_stops = v.get("pit_stops", [])
        if isinstance(pit_stops, list):
            entry["pit_stop_count"] = len(pit_stops)

        entry = {k: v for k, v in entry.items() if v is not None}
        results.append(entry)

    return race_info, results


def merge_live_extras(da_results: list[dict], live_results: list[dict]) -> list[dict]:
    """Merge live-feed extras into DriverAverages results by driver name."""
    # Build lookup by normalized driver name
    live_lookup = {}
    for lr in live_results:
        key = normalize_driver(lr.get("Driver", "")).lower()
        live_lookup[key] = lr

    merged_count = 0
    for dr in da_results:
        key = normalize_driver(dr.get("Driver", "")).lower()
        live = live_lookup.get(key)
        if live:
            # Only add EXTRA fields that DA doesn't have
            extras = [
                "avg_speed", "best_lap_speed", "best_lap_time", "avg_restart_speed",
                "passes_made", "quality_passes", "passing_diff",
                "laps_pos_improved", "fastest_laps_run", "pit_stop_count", "driver_id",
            ]
            for field in extras:
                if field in live and field not in dr:
                    dr[field] = live[field]
            # Use live Start if DA didn't have it
            if "Start" not in dr and "Start" in live:
                dr["Start"] = live["Start"]
            merged_count += 1

    logger.info(f"Merged live-feed extras into {merged_count}/{len(da_results)} drivers")
    return da_results


# ─── NASCAR.com Schedule Helper ───────────────────────────────────────────────

def get_nascar_schedule(year: int, series_id: int = 1) -> list[dict]:
    """Get the NASCAR.com race schedule to map race_id -> race_num."""
    url = NASCAR_SCHEDULE_URL.format(year=year, series_id=series_id)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # When fetching all series, keys are series_1, series_2, etc.
            return data.get(f"series_{series_id}", [])
    except:
        return []


# ─── DB Import (matches parquet importer format) ─────────────────────────────

async def import_race_results(
    conn,
    sport_id: int,
    series: str,
    season: int,
    race_num: int,
    track: str,
    results: list[dict],
    progress_callback=None,
) -> dict:
    """Import a single race's results into the DB.
    Produces metadata identical to the parquet importer."""

    new_count = 0
    updated_count = 0

    # Mapping: raw key -> standardized key (same as parquet importer)
    field_mapping = {
        "Driver": "driver_name",
        "Finish": "finish",
        "Start": "start",
        "Manufacturer": "make",
        "Pts": "pts",
        "Laps": "laps",
        "Led": "led",
        "Status": "status",
        "Team": "team",
        "Rating": "rating",
        "Number": "car_number",
    }

    for entry in results:
        try:
            driver = entry.get("Driver", "Unknown")

            # Build metadata with dual keys (raw + standardized) just like parquet
            metadata = {
                "Season": season,
                "season": season,
                "Race": race_num,
                "race_num": race_num,
                "Track": track,
                "track": track,
            }

            for raw_key, val in entry.items():
                if val is None:
                    continue
                metadata[raw_key] = val
                if raw_key in field_mapping:
                    metadata[field_mapping[raw_key]] = val

            # Ensure critical fields
            if "driver_name" not in metadata:
                metadata["driver_name"] = driver
            if "finish" not in metadata:
                metadata["finish"] = entry.get("Finish")

            # Mark source
            metadata["_source"] = "supplemental"

            content_hash = compute_hash({
                "sport": "nascar",
                "series": series,
                "season": season,
                "driver": driver,
                "track": track,
                "race_num": race_num,
            })

            is_new = await conn.fetchval(
                """INSERT INTO results (sport_id, season, series, track, metadata, content_hash)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (content_hash)
                   DO UPDATE SET metadata = EXCLUDED.metadata
                   RETURNING (xmax = 0)""",
                sport_id, season, series, track, json.dumps(metadata), content_hash,
            )
            if is_new:
                new_count += 1
            else:
                updated_count += 1
        except Exception as e:
            logger.error(f"Error importing {driver} at {track}: {e}")

    if progress_callback:
        progress_callback(f"Race {race_num} {track}: {new_count} new, {updated_count} updated")

    return {"total": new_count + updated_count, "new": new_count, "updated": updated_count}


# ─── Orchestration ────────────────────────────────────────────────────────────

async def run_supplemental_import(
    year: int = None,
    series: str = "cup",
    progress_callback=None,
) -> dict:
    """
    Main entry point. Scrapes DriverAverages for all completed races in the
    season, enriches the latest race with NASCAR.com live-feed extras, and
    imports into the DB.

    Returns summary dict like parquet importer: {rows, new, updated}.
    """
    if year is None:
        year = datetime.now().year

    series_id_map = {"cup": 1, "xfinity": 2, "trucks": 3}
    series_id = series_id_map.get(series, 1)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = 'nascar'")
        if not sport_id:
            sport_id = await conn.fetchval("INSERT INTO sports (name) VALUES ('nascar') RETURNING id")

        summary = {"rows": 0, "new": 0, "updated": 0}

        # ── Step 1: Get the list of completed races from DriverAverages ──
        if progress_callback:
            progress_callback(f"Fetching {year} {series} race list from DriverAverages...")

        da_races = get_da_race_list(year, series)
        if not da_races:
            logger.warning(f"No races found on DriverAverages for {series}")
            return summary

        # ── Step 2: Get NASCAR.com schedule for race_num mapping ──
        nascar_schedule = get_nascar_schedule(year, series_id)
        # Build ordered list of point races and race_id lookup
        point_races_ordered = []  # list of {race_num, track, race_id}
        schedule_by_race_id = {}
        point_race_num = 0
        for sched_race in nascar_schedule:
            # Only count point races (race_type_id == 1)
            if sched_race.get("race_type_id") == 1:
                point_race_num += 1
                track_name = sched_race.get("track_name", "")
                entry = {"race_num": point_race_num, "track": track_name}
                point_races_ordered.append(entry)
                schedule_by_race_id[sched_race.get("race_id")] = entry

        # ── Step 3: Fetch live feed for latest-race enrichment ──
        live_feed_data = fetch_live_feed(series)
        live_race_info = None
        live_results = []
        live_race_num = None
        if live_feed_data:
            live_race_info, live_results = parse_live_feed(live_feed_data)
            rid = live_race_info.get("race_id")
            if rid and rid in schedule_by_race_id:
                live_race_num = schedule_by_race_id[rid]["race_num"]
                logger.info(f"Live feed: {live_race_info['track']} (race_num={live_race_num}, {len(live_results)} drivers)")

        # ── Step 4: Scrape + import each race ──
        for i, da_race in enumerate(da_races):
            sked_id = da_race["sked_id"]
            da_track = da_race["track"]

            # DA races are in chronological order — use index to match
            # against the ordered point-race list from NASCAR.com schedule
            if i < len(point_races_ordered):
                race_num = point_races_ordered[i]["race_num"]
                # Use the official track name from the schedule
                da_track = point_races_ordered[i]["track"] or da_track
            else:
                race_num = i + 1

            if progress_callback:
                progress_callback(f"Scraping race {race_num}/{len(da_races)}: {da_track}...")

            results = scrape_da_race_results(sked_id, series)
            if not results:
                logger.warning(f"No results for {da_track} (sked_id={sked_id})")
                continue

            # Merge live-feed extras if this is the latest race
            if live_race_num and race_num == live_race_num and live_results:
                results = merge_live_extras(results, live_results)

            # Import into DB
            res = await import_race_results(
                conn, sport_id, series, year, race_num, da_track,
                results, progress_callback,
            )
            summary["rows"] += res["total"]
            summary["new"] += res["new"]
            summary["updated"] += res["updated"]

        logger.info(
            f"Supplemental import done: {summary['rows']} total "
            f"({summary['new']} new, {summary['updated']} updated)"
        )
        return summary

    finally:
        await conn.close()


async def run_import(year: int = None, progress_callback=None) -> dict:
    """Import all three series for the given year."""
    if year is None:
        year = datetime.now().year

    total = {"rows": 0, "new": 0, "updated": 0}

    for series in ["cup", "xfinity", "trucks"]:
        if progress_callback:
            progress_callback(f"Starting {series} series...")
        try:
            res = await run_supplemental_import(year, series, progress_callback)
            total["rows"] += res["rows"]
            total["new"] += res["new"]
            total["updated"] += res["updated"]
        except Exception as e:
            logger.error(f"Error importing {series}: {e}")

    return total


# ─── Standalone runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    year = int(sys.argv[1]) if len(sys.argv) > 1 else datetime.now().year
    series = sys.argv[2] if len(sys.argv) > 2 else None

    def log_progress(msg):
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")

    if series:
        result = asyncio.run(run_supplemental_import(year, series, log_progress))
    else:
        result = asyncio.run(run_import(year, log_progress))

    print(f"\n  DONE: {result}")
