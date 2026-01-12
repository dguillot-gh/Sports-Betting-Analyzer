"""
Downloads ALL nflverse data from GitHub releases and imports to PostgreSQL.
Also imports existing Kaggle data.

Data Sources:
- player_stats: Weekly player stats
- players: Player directory
- schedules: Games + betting lines
- ftn_charting: Advanced charting data
- weekly_rosters: Who played each week
NFL Data Importer
Downloads nflverse data from GitHub releases and imports to PostgreSQL.
Also imports existing Kaggle data.

Usage:
    await import_all_nfl(clear_existing=False)
"""

import asyncio
import logging
import json
import hashlib
import gc  # Garbage collection for memory management
import requests
from pathlib import Path
from datetime import datetime
# import pandas as pd  <-- Moved to local function scope
# import asyncpg  <-- Moved to local function scope

logger = logging.getLogger(__name__)

# Database URL
from src.config import DATABASE_URL

# nflverse GitHub data sources
NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
NFLVERSE_PBP_BASE = "https://github.com/nflverse/nflverse-pbp/releases/download"

# Years to import - extended to 2016+ for Next Gen Stats coverage
# 2025 season uses PBP aggregation since nflverse hasn't published stats files for ongoing season
IMPORT_YEARS = list(range(2016, 2025))  # Extended from 2020 to 2016 for NGS
IMPORT_YEARS_MODERN = list(range(2020, 2025))  # Modern seasons for full stats

# Per-season weekly player stats from nflverse-data releases
# URL format: https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_YYYY.csv
PLAYER_STATS_WEEKLY = {
    year: f"{NFLVERSE_BASE}/player_stats/player_stats_{year}.csv"
    for year in IMPORT_YEARS_MODERN  # Weekly stats only reliable from 2020+
}

# Season-level aggregates (pre-computed by nflverse)
PLAYER_STATS_SEASON = {
    year: f"{NFLVERSE_BASE}/player_stats/player_stats_season_{year}.csv"
    for year in IMPORT_YEARS_MODERN
}

# Supporting data files
NFLVERSE_FILES = {
    "players": f"{NFLVERSE_BASE}/players/players.csv",
    # Schedules and rosters fetched via library now
}

# ============== NEW: COMPREHENSIVE NFLVERSE DATASETS ==============

# Next Gen Stats (available from 2016+)
# Player-level tracking data: speed, separation, time to throw, etc.
NEXTGEN_STATS = {
    "passing": f"{NFLVERSE_BASE}/nextgen_stats/ngs_passing.parquet",
    "rushing": f"{NFLVERSE_BASE}/nextgen_stats/ngs_rushing.parquet",
    "receiving": f"{NFLVERSE_BASE}/nextgen_stats/ngs_receiving.parquet",
}

# Snap Counts (available from 2012+)
# URL format: snap_counts/snap_counts_{year}.parquet
SNAP_COUNTS_BASE = f"{NFLVERSE_BASE}/snap_counts/snap_counts_{{year}}.parquet"

# Combine Data (available from 2000+)
# Athletic measurables from NFL Combine
COMBINE_URL = f"{NFLVERSE_BASE}/combine/combine.parquet"

# Draft Picks (available from 2000+)
DRAFT_PICKS_URL = f"{NFLVERSE_BASE}/draft_picks/draft_picks.parquet"

# Team Descriptions (logos, colors, etc.)
TEAMS_URL = f"{NFLVERSE_BASE}/teams/teams_colors_logos.parquet"

# Injuries (historical, 2009-2024)
# URL format: injuries/injuries_{year}.parquet
INJURIES_BASE = f"{NFLVERSE_BASE}/injuries/injuries_{{year}}.parquet"

# Contracts (historical)
CONTRACTS_URL = f"{NFLVERSE_BASE}/contracts/historical_contracts.parquet"

# PFR Advanced Stats - Use source filenames for consistency
ADVANCED_STATS = {
    "advstats_season_pass": f"{NFLVERSE_BASE}/pfr_advstats/advstats_season_pass.parquet",
    "advstats_season_rush": f"{NFLVERSE_BASE}/pfr_advstats/advstats_season_rush.parquet",
    "advstats_season_rec": f"{NFLVERSE_BASE}/pfr_advstats/advstats_season_rec.parquet",
    "advstats_season_def": f"{NFLVERSE_BASE}/pfr_advstats/advstats_season_def.parquet",
}

# 2025 season data (play-by-play files, per game)
PBP_2025_TAG = "raw_pbp_2025"

# Local data paths
DATA_DIR = Path("/app/data/nfl")
NFLVERSE_DIR = Path("/app/data/nflverse")
NGS_DIR = NFLVERSE_DIR / "nextgen_stats"
ADVANCED_DIR = NFLVERSE_DIR / "advanced_stats"



def compute_hash(data: dict) -> str:
    """Compute hash for deduplication."""
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def download_nflverse(progress_callback=None):
    """Download latest nflverse data from GitHub releases."""
    NFLVERSE_DIR.mkdir(parents=True, exist_ok=True)
    
    downloaded = []
    
    # Download per-year season stats (2020-2024 - 2025 uses PBP)
    for year, url in PLAYER_STATS_SEASON.items():
        try:
            name = f"player_stats_season_{year}"
            if progress_callback:
                progress_callback(f"Downloading {name}.csv...")
            
            response = requests.get(url, timeout=120)
            if response.status_code == 200:
                file_path = NFLVERSE_DIR / f"{name}.csv"
                file_path.write_bytes(response.content)
                downloaded.append(name)
                logger.info(f"Downloaded {name}.csv ({len(response.content)} bytes)")
            else:
                logger.warning(f"Failed to download {name}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading stats for {year}: {e}")
    
    # Download supporting files (players)
    for name, url in NFLVERSE_FILES.items():
        try:
            if progress_callback:
                progress_callback(f"Downloading {name}.csv...")
            
            response = requests.get(url, timeout=120)
            if response.status_code == 200:
                file_path = NFLVERSE_DIR / f"{name}.csv"
                file_path.write_bytes(response.content)
                downloaded.append(name)
                logger.info(f"Downloaded {name}.csv ({len(response.content)} bytes)")
            else:
                logger.warning(f"Failed to download {name}: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading {name}: {e}")

    # Fetch Schedules and Rosters via nflreadpy (preferred) or nfl_data_py (legacy)
    try:
        if progress_callback:
            progress_callback("Fetching schedules and rosters from nflverse...")
        
        # Schedules
        try:
            schedule_years = IMPORT_YEARS + [max(IMPORT_YEARS) + 1]
            
            # Try nflreadpy first (actively maintained)
            try:
                import nflreadpy as nfl
                sched_polars = nfl.load_schedules(schedule_years)
                sched = sched_polars.to_pandas()
                logger.info(f"Downloaded schedules via nflreadpy ({len(sched)} games)")
            except ImportError:
                import nfl_data_py as nfl
                sched = nfl.import_schedules(schedule_years)
                logger.info(f"Downloaded schedules via nfl_data_py ({len(sched)} games)")
            
            sched.to_csv(NFLVERSE_DIR / "schedules.csv", index=False)
            downloaded.append("schedules")
        except Exception as e:
            logger.error(f"Error fetching schedules: {e}")

        # Rosters
        try:
            try:
                import nflreadpy as nfl
                rosters_polars = nfl.load_rosters(IMPORT_YEARS)
                rosters = rosters_polars.to_pandas()
                rosters.to_csv(NFLVERSE_DIR / "roster.csv", index=False)
                downloaded.append("rosters")
                logger.info(f"Downloaded rosters via nflreadpy ({len(rosters)} rows)")
            except ImportError:
                try:
                    import nfl_data_py as nfl
                    rosters = nfl.import_weekly_rosters(IMPORT_YEARS)
                    rosters.to_csv(NFLVERSE_DIR / "roster.csv", index=False)
                    downloaded.append("rosters")
                    logger.info(f"Downloaded rosters via nfl_data_py ({len(rosters)} rows)")
                except ImportError:
                    # Fallback: Direct HTTP download of combined rosters
                    logger.warning("Neither nflreadpy nor nfl_data_py installed, using direct HTTP download for rosters")
                    roster_dfs = []
                    import pandas as pd
                    for year in IMPORT_YEARS:
                        try:
                            url = f"{NFLVERSE_BASE}/rosters/roster_{year}.parquet"
                            response = requests.get(url, timeout=60)
                            if response.status_code == 200:
                                import io
                                df = pd.read_parquet(io.BytesIO(response.content))
                                roster_dfs.append(df)
                                logger.info(f"Downloaded roster_{year}.parquet ({len(df)} rows)")
                        except Exception as e:
                            logger.warning(f"Failed to download roster {year}: {e}")
                    
                    if roster_dfs:
                        full_rosters = pd.concat(roster_dfs, ignore_index=True)
                        full_rosters.to_csv(NFLVERSE_DIR / "roster.csv", index=False)
                        downloaded.append("rosters")
                        logger.info(f"Saved aggregated rosters: {len(full_rosters)} rows")
        except Exception as e:
            logger.error(f"Error fetching rosters: {e}")
            
    except Exception as e:
        logger.error(f"Library import failed: {e}")
    
    return downloaded


async def download_comprehensive_nflverse(progress_callback=None) -> dict:
    """
    Download comprehensive nflverse datasets for advanced analytics.
    Includes: Next Gen Stats, Snap Counts, Combine, Draft Picks, Contracts, etc.
    
    Returns dict with download status for each dataset type.
    """
    import pyarrow.parquet as pq
    import io
    
    results = {
        "nextgen_stats": {"status": "pending", "files": []},
        "snap_counts": {"status": "pending"},
        "combine": {"status": "pending"},
        "draft_picks": {"status": "pending"},
        "injuries": {"status": "pending"},
        "contracts": {"status": "pending"},
        "teams": {"status": "pending"},
        "advanced_stats": {"status": "pending", "files": []},
    }
    
    # Create directories
    NGS_DIR.mkdir(parents=True, exist_ok=True)
    ADVANCED_DIR.mkdir(parents=True, exist_ok=True)
    
    # 0. Download basic nflverse data (Players, Schedules, Rosters, Stats)
    if progress_callback:
        progress_callback("Checking basic NFLverse data (rosters, schedules)...")
    
    basic_results = await download_nflverse(progress_callback)
    
    # Helper to download and save parquet files
    async def download_parquet(url: str, save_path: Path, name: str) -> bool:
        try:
            if progress_callback:
                progress_callback(f"Downloading {name}...")
            
            response = requests.get(url, timeout=300)
            if response.status_code == 200:
                # Save raw parquet file
                save_path.write_bytes(response.content)
                
                # Try to read and get row count for logging
                try:
                    table = pq.read_table(save_path)
                    row_count = table.num_rows
                    logger.info(f"Downloaded {name}: {row_count:,} rows")
                except Exception:
                    logger.info(f"Downloaded {name}: {len(response.content):,} bytes")
                
                return True
            else:
                logger.warning(f"Failed to download {name}: HTTP {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error downloading {name}: {e}")
            return False
    
    # 1. Download Next Gen Stats (passing, rushing, receiving)
    ngs_success = []
    for stat_type, url in NEXTGEN_STATS.items():
        save_path = NGS_DIR / f"ngs_{stat_type}.parquet"
        if await download_parquet(url, save_path, f"NGS {stat_type}"):
            ngs_success.append(stat_type)
    
    results["nextgen_stats"]["status"] = "success" if ngs_success else "failed"
    results["nextgen_stats"]["files"] = ngs_success
    
    # 2. Download Snap Counts (2012-2024) - Aggregate yearly files
    snap_success = True
    snap_dfs = []
    
    for year in range(2012, 2025):
        try:
            import pandas as pd
            url = SNAP_COUNTS_BASE.format(year=year)
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                with io.BytesIO(response.content) as buffer:
                    df = pd.read_parquet(buffer)
                    snap_dfs.append(df)
            else:
                logger.warning(f"Failed to download Snap Counts {year}: HTTP {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading Snap Counts {year}: {e}")
            
    if snap_dfs:
        try:
            full_snaps = pd.concat(snap_dfs, ignore_index=True)
            snap_path = NFLVERSE_DIR / "snap_counts.parquet"
            full_snaps.to_parquet(snap_path)
            logger.info(f"Saved aggregated Snap Counts: {len(full_snaps):,} rows")
            results["snap_counts"]["status"] = "success"
        except Exception as e:
            logger.error(f"Error saving aggregated Snap Counts: {e}")
            results["snap_counts"]["status"] = "failed"
    else:
        results["snap_counts"]["status"] = "failed"
    
    # 3. Download Combine Data
    combine_path = NFLVERSE_DIR / "combine.parquet"
    results["combine"]["status"] = "success" if await download_parquet(
        COMBINE_URL, combine_path, "Combine Data"
    ) else "failed"
    
    # 4. Download Draft Picks
    draft_path = NFLVERSE_DIR / "draft_picks.parquet"
    results["draft_picks"]["status"] = "success" if await download_parquet(
        DRAFT_PICKS_URL, draft_path, "Draft Picks"
    ) else "failed"
    
    # 5. Download Teams metadata (Teams Colors & Logos)
    teams_path = NFLVERSE_DIR / "teams.parquet"
    results["teams"]["status"] = "success" if await download_parquet(
        TEAMS_URL, teams_path, "Teams"
    ) else "failed"
    
    # 6. Download Injuries (historical, 2009-2024) - Aggregate yearly files
    inj_dfs = []
    
    for year in range(2009, 2025):
        try:
            url = INJURIES_BASE.format(year=year)
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                with io.BytesIO(response.content) as buffer:
                    df = pd.read_parquet(buffer)
                    inj_dfs.append(df)
        except Exception as e:
            logger.warning(f"Error downloading Injuries {year}: {e}")
            
    if inj_dfs:
        try:
            full_inj = pd.concat(inj_dfs, ignore_index=True)
            injuries_path = NFLVERSE_DIR / "injuries.parquet"
            full_inj.to_parquet(injuries_path)
            logger.info(f"Saved aggregated Injuries: {len(full_inj):,} rows")
            results["injuries"]["status"] = "success"
        except Exception as e:
            logger.error(f"Error saving aggregated Injuries: {e}")
            results["injuries"]["status"] = "failed"
    else:
        results["injuries"]["status"] = "failed"
    
    # 7. Download Contracts (Historical) - uses source filename
    contracts_path = NFLVERSE_DIR / "historical_contracts.parquet"
    results["contracts"]["status"] = "success" if await download_parquet(
        CONTRACTS_URL, contracts_path, "Contracts"
    ) else "failed"
    
    # 8. Download PFR Advanced Stats
    adv_success = []
    for stat_type, url in ADVANCED_STATS.items():
        save_path = ADVANCED_DIR / f"{stat_type}.parquet"
        if await download_parquet(url, save_path, f"PFR {stat_type}"):
            adv_success.append(stat_type)
    
    results["advanced_stats"]["status"] = "success" if adv_success else "failed"
    results["advanced_stats"]["files"] = adv_success
    
    # Summary
    success_count = sum(1 for v in results.values() if v.get("status") == "success")
    logger.info(f"Comprehensive nflverse download complete: {success_count}/{len(results)} datasets")
    
    if progress_callback:
        progress_callback(f"Downloaded {success_count}/{len(results)} comprehensive datasets")
    
    return results


async def download_pbp_2025(progress_callback=None) -> list:
    """Download 2025 play-by-play RDS files from nflverse-pbp releases."""
    import gzip
    
    PBP_DIR = NFLVERSE_DIR / "pbp_2025"
    PBP_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get list of available files from GitHub API
    api_url = f"https://api.github.com/repos/nflverse/nflverse-pbp/releases/tags/{PBP_2025_TAG}"
    
    try:
        if progress_callback:
            progress_callback("Fetching 2025 PBP file list...")
        
        response = requests.get(api_url, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Failed to get PBP 2025 release info: {response.status_code}")
            return []
        
        release_data = response.json()
        assets = release_data.get("assets", [])
        
        # Filter for .rds files (smaller than .json.gz)
        rds_files = [a for a in assets if a["name"].endswith(".rds")]
        
        if progress_callback:
            progress_callback(f"Found {len(rds_files)} PBP game files for 2025...")
        
        downloaded = []
        for i, asset in enumerate(rds_files):
            name = asset["name"]
            url = asset["browser_download_url"]
            
            file_path = PBP_DIR / name
            
            # Skip if already downloaded
            if file_path.exists():
                downloaded.append(name)
                continue
            
            try:
                if progress_callback and i % 20 == 0:
                    progress_callback(f"Downloading PBP {i+1}/{len(rds_files)}: {name}...")
                
                resp = requests.get(url, timeout=60)
                if resp.status_code == 200:
                    file_path.write_bytes(resp.content)
                    downloaded.append(name)
                    logger.info(f"Downloaded {name}")
            except Exception as e:
                logger.error(f"Error downloading {name}: {e}")
        
        logger.info(f"Downloaded {len(downloaded)} PBP 2025 files")
        return downloaded
    
    except Exception as e:
        logger.error(f"Error fetching PBP 2025 list: {e}")
        return []


async def import_pbp_2025(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import 2025 player stats from play-by-play RDS files.
    
    Args:
        conn: Database connection
        sport_id: NFL sport ID
        player_map: Dict mapping player_id -> entity_id for stats table insertion
        progress_callback: Optional progress callback function
    """
    try:
        import pyreadr
    except ImportError:
        logger.error("pyreadr not installed. Run: pip install pyreadr")
        return {"error": "pyreadr not installed"}
    
    PBP_DIR = NFLVERSE_DIR / "pbp_2025"
    rds_files = sorted(PBP_DIR.glob("*.rds"))
    
    if not rds_files:
        logger.warning("No PBP 2025 RDS files found")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback(f"Processing {len(rds_files)} PBP 2025 game files...")
    
    # Aggregate player stats across all games
    player_stats = {}  # player_id -> cumulative stats
    games_processed = 0
    
    for i, rds_file in enumerate(rds_files):
        try:
            import pandas as pd
            if progress_callback and i % 20 == 0:
                progress_callback(f"Processing game {i+1}/{len(rds_files)}: {rds_file.name}...")
            
            # Read RDS file
            result = pyreadr.read_r(str(rds_file))
            if not result:
                continue
            
            df = list(result.values())[0]
            
            # Aggregate stats by player from play-by-play
            # Common columns: passer_player_id, rusher_player_id, receiver_player_id
            # Stats: passing_yards, rushing_yards, receiving_yards, etc.
            
            for _, play in df.iterrows():
                # Passing stats
                passer_id = play.get('passer_player_id')
                if passer_id and not pd.isna(passer_id):
                    if passer_id not in player_stats:
                        player_stats[passer_id] = {
                            'player_id': str(passer_id),
                            'player_name': play.get('passer_player_name'),
                            'position': 'QB',
                            'team': play.get('posteam'),
                            'season': 2025,
                            'games': set(),
                            'pass_att': 0, 'pass_cmp': 0, 'pass_yds': 0, 'pass_td': 0, 'pass_int': 0,
                            'rush_att': 0, 'rush_yds': 0, 'rush_td': 0,
                            'rec': 0, 'targets': 0, 'rec_yds': 0, 'rec_td': 0,
                        }
                    player_stats[passer_id]['games'].add(play.get('game_id'))
                    if play.get('pass_attempt') == 1:
                        player_stats[passer_id]['pass_att'] += 1
                    if play.get('complete_pass') == 1:
                        player_stats[passer_id]['pass_cmp'] += 1
                    player_stats[passer_id]['pass_yds'] += int(play.get('passing_yards') or 0)
                    if play.get('pass_touchdown') == 1:
                        player_stats[passer_id]['pass_td'] += 1
                    if play.get('interception') == 1:
                        player_stats[passer_id]['pass_int'] += 1
                
                # Rushing stats
                rusher_id = play.get('rusher_player_id')
                if rusher_id and not pd.isna(rusher_id):
                    if rusher_id not in player_stats:
                        player_stats[rusher_id] = {
                            'player_id': str(rusher_id),
                            'player_name': play.get('rusher_player_name'),
                            'position': 'RB',
                            'team': play.get('posteam'),
                            'season': 2025,
                            'games': set(),
                            'pass_att': 0, 'pass_cmp': 0, 'pass_yds': 0, 'pass_td': 0, 'pass_int': 0,
                            'rush_att': 0, 'rush_yds': 0, 'rush_td': 0,
                            'rec': 0, 'targets': 0, 'rec_yds': 0, 'rec_td': 0,
                        }
                    player_stats[rusher_id]['games'].add(play.get('game_id'))
                    if play.get('rush_attempt') == 1:
                        player_stats[rusher_id]['rush_att'] += 1
                    player_stats[rusher_id]['rush_yds'] += int(play.get('rushing_yards') or 0)
                    if play.get('rush_touchdown') == 1:
                        player_stats[rusher_id]['rush_td'] += 1
                
                # Receiving stats
                receiver_id = play.get('receiver_player_id')
                if receiver_id and not pd.isna(receiver_id):
                    if receiver_id not in player_stats:
                        player_stats[receiver_id] = {
                            'player_id': str(receiver_id),
                            'player_name': play.get('receiver_player_name'),
                            'position': 'WR',
                            'team': play.get('posteam'),
                            'season': 2025,
                            'games': set(),
                            'pass_att': 0, 'pass_cmp': 0, 'pass_yds': 0, 'pass_td': 0, 'pass_int': 0,
                            'rush_att': 0, 'rush_yds': 0, 'rush_td': 0,
                            'rec': 0, 'targets': 0, 'rec_yds': 0, 'rec_td': 0,
                        }
                    player_stats[receiver_id]['games'].add(play.get('game_id'))
                    player_stats[receiver_id]['targets'] += 1
                    if play.get('complete_pass') == 1:
                        player_stats[receiver_id]['rec'] += 1
                    player_stats[receiver_id]['rec_yds'] += int(play.get('receiving_yards') or 0)
                    if play.get('pass_touchdown') == 1:
                        player_stats[receiver_id]['rec_td'] += 1
            
            games_processed += 1
            gc.collect()
            
        except Exception as e:
            logger.error(f"Error processing {rds_file.name}: {e}")
    
    # Insert aggregated stats into database
    if progress_callback:
        progress_callback(f"Inserting {len(player_stats)} player season stats for 2025...")
    
    imported = 0
    for player_id, stats in player_stats.items():
        # Convert games set to count
        stats['games'] = len(stats['games'])
        
        # Clean metadata
        metadata = {k: v for k, v in stats.items() if v is not None and v != 0}
        
        content_hash = compute_hash({
            'sport': 'nfl',
            'player_id': str(player_id),
            'season': 2025,
            'type': 'season_stats'
        })
        
        try:
            # Insert into results table (for game history queries)
            await conn.execute(
                """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                   VALUES ($1, $2, 'nfl', $3, $4)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET metadata = EXCLUDED.metadata""",
                sport_id, 2025, json.dumps(metadata), content_hash
            )
            
            # ALSO insert into stats table (for profile queries)
            # First try to look up entity_id from player_map
            entity_id = player_map.get(str(player_id))
            
            # If not in player_map, try to find by searching entities table
            if not entity_id:
                player_name = stats.get('player_name', '')
                if player_name:
                    entity_id = await conn.fetchval(
                        """SELECT id FROM entities 
                           WHERE sport_id = $1 AND name ILIKE $2
                           LIMIT 1""",
                        sport_id, f"%{player_name}%"
                    )
            
            if entity_id:
                # Build stats dict (exclude identifier fields)
                stats_dict = {k: v for k, v in metadata.items() 
                             if k not in ['player_id', 'player_name', 'games'] and v is not None}
                stats_dict['games'] = metadata.get('games', 0)  # Keep games count
                
                stats_hash = compute_hash({
                    'entity_id': entity_id,
                    'season': 2025,
                    'sport': 'nfl',
                    'stat_type': 'season'
                })
                
                await conn.execute(
                    """INSERT INTO stats (entity_id, season, stat_type, stats, content_hash)
                       VALUES ($1, $2, 'season', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET stats = EXCLUDED.stats""",
                    entity_id, 2025, json.dumps(stats_dict), stats_hash
                )
            
            imported += 1
        except Exception as e:
            logger.debug(f"Error inserting player {player_id}: {e}")
    
    logger.info(f"Processed {games_processed} games, imported {imported} player 2025 stats to results AND stats tables")
    return {"games_processed": games_processed, "imported": imported}


async def get_db_connection():
    """Get database connection."""
    import asyncpg
    return await asyncpg.connect(DATABASE_URL)


async def ensure_schema(conn):
    """Ensure required columns exist in database tables."""
    try:
        # Relax overly strict unique constraint on entities (players can have same name)
        await conn.execute("ALTER TABLE entities DROP CONSTRAINT IF EXISTS entities_sport_id_name_type_series_key")
        await conn.execute("ALTER TABLE entities DROP CONSTRAINT IF EXISTS entities_sport_id_name_type_key")
        
        await conn.execute("ALTER TABLE entities ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("ALTER TABLE results ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("ALTER TABLE stats ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_hash ON entities(content_hash) WHERE content_hash IS NOT NULL")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_results_hash ON results(content_hash) WHERE content_hash IS NOT NULL")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stats_hash ON stats(content_hash) WHERE content_hash IS NOT NULL")
        logger.info("Schema setup complete - content_hash columns ready and constraints relaxed")
    except Exception as e:
        logger.warning(f"Schema setup warning: {e}")


async def ensure_sport_exists(conn) -> int:
    """Ensure NFL sport exists and return sport_id."""
    sport_id = await conn.fetchval(
        "SELECT id FROM sports WHERE name = 'nfl'"
    )
    if not sport_id:
        sport_id = await conn.fetchval(
            """INSERT INTO sports (name, config) 
               VALUES ('nfl', '{}') 
               RETURNING id"""
        )
    return sport_id


# Batch size for commits to prevent memory issues
BATCH_SIZE = 1000


async def import_stats_via_nflreadpy(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import player stats using nflreadpy - handles all years including 2025.
    
    This uses the official nflverse Python package which:
    - Handles data fetching and caching automatically
    - Provides pre-aggregated season stats via summary_level="reg"
    - Includes current (2025) season data
    """
    try:
        import nflreadpy as nfl
    except ImportError:
        logger.error("nflreadpy not installed. Run: pip install nflreadpy")
        return {"error": "nflreadpy not installed", "imported": 0}
    
    if progress_callback:
        progress_callback("Loading player stats from nflverse (2020-2025)...")
    
    imported = 0
    stats_computed = 0
    
    try:
        # Get season-level aggregates for all years in one call
        # summary_level="reg" gives us regular season totals pre-aggregated
        stats_df = nfl.load_player_stats(
            seasons=[2020, 2021, 2022, 2023, 2024, 2025],
            summary_level="reg"
        ).to_pandas()
        
        if progress_callback:
            progress_callback(f"Processing {len(stats_df)} player-season records...")
        
        logger.info(f"Loaded {len(stats_df)} player-season records from nflreadpy")
        
        for i, (_, row) in enumerate(stats_df.iterrows()):
            if progress_callback and i % 500 == 0:
                progress_callback(f"Processing player stats {i}/{len(stats_df)}...")
            
            player_id = row.get('player_id')
            if pd.isna(player_id):
                continue
            
            season = row.get('season')
            if pd.isna(season):
                continue
            
            # Build metadata with all available stats
            def safe_val(val):
                if pd.isna(val):
                    return None
                if isinstance(val, float):
                    return int(val) if val == int(val) else round(val, 2)
                return val
            
            metadata = {
                'player_id': str(player_id),
                'player_name': safe_val(row.get('player_display_name') or row.get('player_name')),
                'position': safe_val(row.get('position')),
                'team': safe_val(row.get('recent_team')),
                'season': int(season),
                'games': safe_val(row.get('games')),
                # Passing
                'pass_att': safe_val(row.get('attempts')),
                'pass_cmp': safe_val(row.get('completions')),
                'pass_yds': safe_val(row.get('passing_yards')),
                'pass_td': safe_val(row.get('passing_tds')),
                'pass_int': safe_val(row.get('interceptions')),
                # Rushing
                'rush_att': safe_val(row.get('carries')),
                'rush_yds': safe_val(row.get('rushing_yards')),
                'rush_td': safe_val(row.get('rushing_tds')),
                # Receiving  
                'rec': safe_val(row.get('receptions')),
                'targets': safe_val(row.get('targets')),
                'rec_yds': safe_val(row.get('receiving_yards')),
                'rec_td': safe_val(row.get('receiving_tds')),
                # Fantasy
                'fantasy_pts': safe_val(row.get('fantasy_points')),
                'fantasy_pts_ppr': safe_val(row.get('fantasy_points_ppr')),
            }
            
            # Remove None values
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            content_hash = compute_hash({
                'sport': 'nfl',
                'player_id': str(player_id),
                'season': int(season),
                'type': 'season_stats'
            })
            
            try:
                # Insert into results table
                await conn.execute(
                    """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                       VALUES ($1, $2, 'nfl', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET metadata = EXCLUDED.metadata""",
                    sport_id, int(season), json.dumps(metadata), content_hash
                )
                
                # ALSO insert into stats table (for profile queries)
                entity_id = player_map.get(str(player_id))
                
                # If not in player_map, try name-based lookup
                if not entity_id:
                    player_name = metadata.get('player_name', '')
                    if player_name:
                        entity_id = await conn.fetchval(
                            """SELECT id FROM entities 
                               WHERE sport_id = $1 AND name ILIKE $2
                               LIMIT 1""",
                            sport_id, f"%{player_name}%"
                        )
                
                if entity_id:
                    stats_dict = {k: v for k, v in metadata.items() 
                                 if k not in ['player_id', 'player_name', 'player_display_name']}
                    
                    stats_hash = compute_hash({
                        'entity_id': entity_id,
                        'season': int(season),
                        'sport': 'nfl',
                        'stat_type': 'season'
                    })
                    
                    await conn.execute(
                        """INSERT INTO stats (entity_id, season, stat_type, stats, content_hash)
                           VALUES ($1, $2, 'season', $3, $4)
                           ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                           DO UPDATE SET stats = EXCLUDED.stats""",
                        entity_id, int(season), json.dumps(stats_dict), stats_hash
                    )
                    stats_computed += 1
                
                imported += 1
                
            except Exception as e:
                logger.debug(f"Error importing stat row: {e}")
            
            # Periodic garbage collection
            if i % 1000 == 0:
                gc.collect()
        
        logger.info(f"Imported {imported} player stats via nflreadpy, {stats_computed} stats table entries")
        return {"imported": imported, "stats_computed": stats_computed}
        
    except Exception as e:
        logger.error(f"Error loading stats via nflreadpy: {e}")
        return {"error": str(e), "imported": 0}


async def import_weekly_stats_via_nflreadpy(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import NFL weekly (game-by-game) stats using nflreadpy for hit rate calculations."""
    try:
        import nflreadpy as nfl
    except ImportError:
        logger.warning("nflreadpy not installed - skipping weekly stats")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback("Loading weekly NFL stats for hit rates...")
    
    imported = 0
    
    try:
        # Load weekly stats (no summary_level = game-by-game data)
        # Only load recent seasons to keep DB size manageable
        weekly_df = nfl.load_player_stats(
            seasons=[2023, 2024, 2025]
        ).to_pandas()
        
        if progress_callback:
            progress_callback(f"Processing {len(weekly_df)} weekly game records...")
        
        logger.info(f"Loaded {len(weekly_df)} weekly stats from nflreadpy")
        
        for i, (_, row) in enumerate(weekly_df.iterrows()):
            if progress_callback and i % 1000 == 0:
                progress_callback(f"Importing weekly stats {i}/{len(weekly_df)}...")
            
            player_id = row.get('player_id')
            if pd.isna(player_id):
                continue
            
            season = row.get('season')
            week = row.get('week')
            if pd.isna(season) or pd.isna(week):
                continue
            
            def safe_val(val):
                if pd.isna(val):
                    return None
                if isinstance(val, float):
                    return int(val) if val == int(val) else round(val, 2)
                return val
            
            metadata = {
                'player_id': str(player_id),
                'player_name': safe_val(row.get('player_display_name') or row.get('player_name')),
                'position': safe_val(row.get('position')),
                'team': safe_val(row.get('recent_team')),
                'season': int(season),
                'week': int(week),
                # Passing
                'pass_att': safe_val(row.get('attempts')),
                'pass_cmp': safe_val(row.get('completions')),
                'pass_yds': safe_val(row.get('passing_yards')),
                'pass_td': safe_val(row.get('passing_tds')),
                'pass_int': safe_val(row.get('interceptions')),
                # Rushing
                'rush_att': safe_val(row.get('carries')),
                'rush_yds': safe_val(row.get('rushing_yards')),
                'rush_td': safe_val(row.get('rushing_tds')),
                # Receiving  
                'rec': safe_val(row.get('receptions')),
                'targets': safe_val(row.get('targets')),
                'rec_yds': safe_val(row.get('receiving_yards')),
                'rec_td': safe_val(row.get('receiving_tds')),
                # Fantasy
                'fantasy_pts': safe_val(row.get('fantasy_points')),
                'fantasy_pts_ppr': safe_val(row.get('fantasy_points_ppr')),
            }
            
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            content_hash = compute_hash({
                'sport': 'nfl',
                'player_id': str(player_id),
                'season': int(season),
                'week': int(week),
                'type': 'weekly_stats'
            })
            
            try:
                await conn.execute(
                    """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                       VALUES ($1, $2, 'nfl_weekly', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET metadata = EXCLUDED.metadata""",
                    sport_id, int(season), json.dumps(metadata), content_hash
                )
                imported += 1
            except Exception as e:
                logger.debug(f"Error importing weekly stat: {e}")
            
            if i % 2000 == 0:
                gc.collect()
        
        logger.info(f"Imported {imported} weekly NFL stats")
        return {"imported": imported}
        
    except Exception as e:
        logger.error(f"Error loading weekly stats: {e}")
        return {"imported": 0, "error": str(e)}


async def import_players_via_nflreadpy(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NFL players using nflreadpy."""
    try:
        import nflreadpy as nfl
    except ImportError:
        logger.error("nflreadpy not installed")
        return {"imported": 0, "player_map": {}}
    
    if progress_callback:
        progress_callback("Loading player data from nflverse...")
    
    try:
        players_df = nfl.load_players().to_pandas()
        
        if progress_callback:
            progress_callback(f"Processing {len(players_df)} players...")
        
        player_map = {}
        imported = 0
        
        for i, (_, row) in enumerate(players_df.iterrows()):
            if progress_callback and i % 500 == 0:
                progress_callback(f"Importing players {i}/{len(players_df)}...")
            
            player_id = row.get('gsis_id') or row.get('player_id')
            if pd.isna(player_id):
                continue
            
            name = row.get('display_name') or row.get('name')
            if pd.isna(name):
                continue
            
            position = row.get('position')
            team = row.get('team_abbr')
            
            metadata = {
                'gsis_id': str(player_id),
                'position': str(position) if not pd.isna(position) else None,
                'team': str(team) if not pd.isna(team) else None,
                'height': str(row.get('height')) if not pd.isna(row.get('height')) else None,
                'weight': str(row.get('weight')) if not pd.isna(row.get('weight')) else None,
            }
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            content_hash = compute_hash({'sport': 'nfl', 'player_id': str(player_id)})
            
            try:
                entity_id = await conn.fetchval(
                    """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                       VALUES ($1, $2, 'player', 'nfl', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                       RETURNING id""",
                    sport_id, str(name), json.dumps(metadata), content_hash
                )
                if entity_id:
                    player_map[str(player_id)] = entity_id
                    imported += 1
            except Exception as e:
                logger.debug(f"Error importing player {name}: {e}")
        
        logger.info(f"Imported {imported} players via nflreadpy")
        return {"imported": imported, "player_map": player_map}
        
    except Exception as e:
        logger.error(f"Error loading players via nflreadpy: {e}")
        return {"imported": 0, "player_map": {}}


async def import_players(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NFL players from nflverse players.csv with batching."""
    players_file = NFLVERSE_DIR / "players.csv"
    if not players_file.exists():
        logger.warning("players.csv not found")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback("Importing players...")
    
    # Map player_id -> entity_id
    player_map = {}
    imported = 0
    batch_count = 0
    
    for chunk in pd.read_csv(players_file, low_memory=False, chunksize=BATCH_SIZE):
        batch_count += 1
        if progress_callback and batch_count % 5 == 0:
            progress_callback(f"Processing player batch {batch_count} ({imported} players imported)...")
        
        for _, row in chunk.iterrows():
            player_id = row.get('gsis_id') or row.get('player_id')
            if not player_id or pd.isna(player_id):
                continue
            
            name = row.get('display_name') or row.get('name') or f"Player {player_id}"
            if pd.isna(name):
                continue
                
            position = row.get('position') or row.get('position_group', '')
            team = row.get('team_abbr') or row.get('current_team_id', '')
            
            metadata = {
                'position': str(position) if not pd.isna(position) else None,
                'team': str(team) if not pd.isna(team) else None,
                'height': row.get('height') if not pd.isna(row.get('height', None)) else None,
                'weight': row.get('weight') if not pd.isna(row.get('weight', None)) else None,
            }
            
            content_hash = compute_hash({'sport': 'nfl', 'player_id': str(player_id)})
            
            try:
                entity_id = await conn.fetchval(
                    """INSERT INTO entities (sport_id, name, type, series, metadata, content_hash)
                       VALUES ($1, $2, 'player', 'nfl', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET name = EXCLUDED.name, metadata = EXCLUDED.metadata
                       RETURNING id""",
                    sport_id, str(name), json.dumps(metadata), content_hash
                )
                if entity_id:
                    player_map[str(player_id)] = entity_id
                    imported += 1
            except Exception as e:
                logger.debug(f"Error importing player {name}: {e}")
    
    logger.info(f"Imported {imported} players")
    return {"imported": imported, "player_map": player_map}


async def import_player_stats(conn, sport_id: int, player_map: dict, progress_callback=None) -> dict:
    """Import player season stats from nflverse player_stats_season_YYYY.csv files."""
    
    # Find all player_stats_season_YYYY.csv files (2020-2024)
    stats_files = sorted(NFLVERSE_DIR.glob("player_stats_season_*.csv"))
    
    if not stats_files:
        logger.warning("No player_stats_season_*.csv files found")
        return {"imported": 0, "stats_computed": 0}
    
    if progress_callback:
        progress_callback(f"Found {len(stats_files)} season stats files to process...")
    
    def safe_int(val):
        try:
            return int(float(val)) if not pd.isna(val) else None
        except:
            return None
    
    def safe_float(val):
        try:
            return round(float(val), 2) if not pd.isna(val) else None
        except:
            return None
    
    imported = 0
    
    for stats_file in stats_files:
        if progress_callback:
            progress_callback(f"Processing {stats_file.name}...")
        
        try:
            # Read CSV in chunks for memory efficiency
            for chunk in pd.read_csv(stats_file, low_memory=False, chunksize=500):
                for _, row in chunk.iterrows():
                    player_id = row.get('player_id')
                    if pd.isna(player_id):
                        continue
                    
                    season = row.get('season')
                    if pd.isna(season):
                        continue
                    
                    # Build metadata with season totals
                    metadata = {
                        'player_id': str(player_id),
                        'player_name': row.get('player_display_name') or row.get('player_name'),
                        'position': row.get('position'),
                        'team': row.get('recent_team'),
                        'season': safe_int(season),
                        'games': safe_int(row.get('games')),
                        # Passing
                        'pass_att': safe_int(row.get('attempts')),
                        'pass_cmp': safe_int(row.get('completions')),
                        'pass_yds': safe_int(row.get('passing_yards')),
                        'pass_td': safe_int(row.get('passing_tds')),
                        'pass_int': safe_int(row.get('passing_interceptions')),
                        'pass_epa': safe_float(row.get('passing_epa')),
                        # Rushing
                        'rush_att': safe_int(row.get('carries')),
                        'rush_yds': safe_int(row.get('rushing_yards')),
                        'rush_td': safe_int(row.get('rushing_tds')),
                        'rush_epa': safe_float(row.get('rushing_epa')),
                        # Receiving
                        'rec': safe_int(row.get('receptions')),
                        'targets': safe_int(row.get('targets')),
                        'rec_yds': safe_int(row.get('receiving_yards')),
                        'rec_td': safe_int(row.get('receiving_tds')),
                        'rec_epa': safe_float(row.get('receiving_epa')),
                        # Defense
                        'tackles': safe_int(row.get('def_tackles_solo')),
                        'sacks': safe_float(row.get('def_sacks')),
                        'def_int': safe_int(row.get('def_interceptions')),
                        # Fantasy
                        'fantasy_pts': safe_float(row.get('fantasy_points')),
                        'fantasy_pts_ppr': safe_float(row.get('fantasy_points_ppr')),
                    }
                    
                    # Clean None values
                    metadata = {k: v for k, v in metadata.items() if v is not None}
                    
                    # Create unique hash for this player-season (for results table)
                    content_hash = compute_hash({
                        'sport': 'nfl',
                        'player_id': str(player_id),
                        'season': season,
                        'type': 'season_stats'
                    })
                    
                    try:
                        # Insert into results table (for game history queries)
                        await conn.execute(
                            """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                               VALUES ($1, $2, 'nfl', $3, $4)
                               ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                               DO UPDATE SET metadata = EXCLUDED.metadata""",
                            sport_id, int(season), json.dumps(metadata), content_hash
                        )
                        
                        # ALSO insert into stats table (for profile queries)
                        # Look up entity_id from player_map
                        entity_id = player_map.get(str(player_id))
                        if entity_id:
                            # Build stats dict (exclude identifier fields)
                            stats_dict = {k: v for k, v in metadata.items() 
                                         if k not in ['player_id', 'player_name', 'player_display_name']}
                            
                            stats_hash = compute_hash({
                                'entity_id': entity_id,
                                'season': int(season),
                                'sport': 'nfl',
                                'stat_type': 'season'
                            })
                            
                            await conn.execute(
                                """INSERT INTO stats (entity_id, season, stat_type, stats, content_hash)
                                   VALUES ($1, $2, 'season', $3, $4)
                                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                                   DO UPDATE SET stats = EXCLUDED.stats""",
                                entity_id, int(season), json.dumps(stats_dict), stats_hash
                            )
                        
                        imported += 1
                    except Exception as e:
                        logger.debug(f"Error importing stat row: {e}")
                
                # Memory cleanup after each chunk
                gc.collect()
        
        except Exception as e:
            logger.error(f"Error processing {stats_file.name}: {e}")
    
    logger.info(f"Imported {imported} player season stats to results AND stats tables")
    return {"imported": imported, "stats_computed": imported}


def compute_season_stats(games: list) -> dict:
    """Compute season aggregates from list of game stats."""
    stats = {
        'games': len(games),
        # Passing
        'pass_att': sum(g.get('pass_att', 0) or 0 for g in games),
        'pass_cmp': sum(g.get('pass_cmp', 0) or 0 for g in games),
        'pass_yds': sum(g.get('pass_yds', 0) or 0 for g in games),
        'pass_td': sum(g.get('pass_td', 0) or 0 for g in games),
        'pass_int': sum(g.get('pass_int', 0) or 0 for g in games),
        # Rushing
        'rush_att': sum(g.get('rush_att', 0) or 0 for g in games),
        'rush_yds': sum(g.get('rush_yds', 0) or 0 for g in games),
        'rush_td': sum(g.get('rush_td', 0) or 0 for g in games),
        # Receiving
        'rec': sum(g.get('rec', 0) or 0 for g in games),
        'rec_yds': sum(g.get('rec_yds', 0) or 0 for g in games),
        'rec_td': sum(g.get('rec_td', 0) or 0 for g in games),
        'targets': sum(g.get('targets', 0) or 0 for g in games),
        # Defense
        'tackles': sum(g.get('tackles', 0) or 0 for g in games),
        'sacks': round(sum(g.get('sacks', 0) or 0 for g in games), 1),
        'def_int': sum(g.get('def_int', 0) or 0 for g in games),
    }
    
    # Per-game averages
    if stats['games'] > 0:
        stats['pass_yds_per_game'] = round(stats['pass_yds'] / stats['games'], 1)
        stats['rush_yds_per_game'] = round(stats['rush_yds'] / stats['games'], 1)
        stats['rec_yds_per_game'] = round(stats['rec_yds'] / stats['games'], 1)
    
    # Completion percentage
    if stats['pass_att'] > 0:
        stats['comp_pct'] = round(100 * stats['pass_cmp'] / stats['pass_att'], 1)
    
    # Yards per carry
    if stats['rush_att'] > 0:
        stats['rush_ypc'] = round(stats['rush_yds'] / stats['rush_att'], 1)
    
    return stats


async def import_all_nfl(clear_existing: bool = False, progress_callback=None) -> dict:
    """
    Main entry point: Download nflverse data and import to PostgreSQL.
    
    Args:
        clear_existing: If True, delete existing NFL data first
        progress_callback: Optional function to report progress
    
    Returns:
        dict with import results
    """
    results = {
        "status": "success",
        "downloaded": [],
        "players_imported": 0,
        "games_imported": 0,
        "stats_computed": 0,
        "errors": []
    }
    
    conn = None
    try:
        # Step 1: Download nflverse data
        if progress_callback:
            progress_callback("Starting NFL data import...")
        
        downloaded = await download_nflverse(progress_callback)
        results["downloaded"] = downloaded
        
        # Step 2: Connect to database
        if progress_callback:
            progress_callback("Connecting to database...")
        
        conn = await get_db_connection()
        
        # Ensure schema has required columns
        await ensure_schema(conn)
        
        sport_id = await ensure_sport_exists(conn)
        
        # Step 3: Clear existing if requested
        if clear_existing:
            if progress_callback:
                progress_callback("Clearing existing NFL data...")
            
            await conn.execute(
                "DELETE FROM results WHERE sport_id = $1",
                sport_id
            )
            await conn.execute(
                "DELETE FROM stats WHERE entity_id IN (SELECT id FROM entities WHERE sport_id = $1)",
                sport_id
            )
            await conn.execute(
                "DELETE FROM entities WHERE sport_id = $1",
                sport_id
            )
        
        # Step 4: Import players (using nflreadpy)
        player_result = await import_players_via_nflreadpy(conn, sport_id, progress_callback)
        results["players_imported"] = player_result.get("imported", 0)
        player_map = player_result.get("player_map", {})
        
        # Step 5: Import player stats using nflreadpy (2020-2025 all in one call!)
        # This uses the official nflverse package with pre-aggregated season stats
        stats_result = await import_stats_via_nflreadpy(conn, sport_id, player_map, progress_callback)
        results["games_imported"] = stats_result.get("imported", 0)
        results["stats_computed"] = stats_result.get("stats_computed", 0)
        
        # Step 6: Import game schedules using nflreadpy
        schedule_result = await import_schedules_via_nflreadpy(conn, sport_id, progress_callback)
        results["schedules_imported"] = schedule_result.get("imported", 0)
        
        # Step 7: Import weekly game-by-game stats for hit rate calculations
        weekly_result = await import_weekly_stats_via_nflreadpy(conn, sport_id, player_map, progress_callback)
        results["weekly_stats_imported"] = weekly_result.get("imported", 0)
        
        if progress_callback:
            progress_callback("NFL import complete!")
        
    except Exception as e:
        logger.error(f"NFL import failed: {e}")
        results["status"] = "failed"
        results["errors"].append(str(e))
        if progress_callback:
            progress_callback(f"❌ Error: {e}")
    finally:
        if conn:
            await conn.close()
    
    return results


async def import_schedules_via_nflreadpy(conn, sport_id: int, progress_callback=None) -> dict:
    """Import NFL game schedules using nflreadpy's load_schedules()."""
    try:
        import nflreadpy as nfl
    except ImportError:
        logger.warning("nflreadpy not installed - skipping schedule import")
        return {"imported": 0}
    
    if progress_callback:
        progress_callback("Loading NFL schedules (2020-2025)...")
    
    imported = 0
    
    try:
        # Load schedules for all years
        schedules_df = nfl.load_schedules(seasons=[2020, 2021, 2022, 2023, 2024, 2025]).to_pandas()
        
        if progress_callback:
            progress_callback(f"Processing {len(schedules_df)} games...")
        
        logger.info(f"Loaded {len(schedules_df)} games from nflreadpy schedules")
        
        for i, (_, row) in enumerate(schedules_df.iterrows()):
            if progress_callback and i % 100 == 0:
                progress_callback(f"Importing schedules {i}/{len(schedules_df)}...")
            
            game_id = row.get('game_id')
            if pd.isna(game_id):
                continue
            
            season = row.get('season')
            week = row.get('week')
            
            def safe_val(val):
                if pd.isna(val):
                    return None
                if isinstance(val, float):
                    return int(val) if val == int(val) else round(val, 2)
                return val
            
            metadata = {
                'game_id': str(game_id),
                'season': safe_val(season),
                'week': safe_val(week),
                'game_type': safe_val(row.get('game_type')),
                'gameday': safe_val(row.get('gameday')),
                'weekday': safe_val(row.get('weekday')),
                'gametime': safe_val(row.get('gametime')),
                'away_team': safe_val(row.get('away_team')),
                'home_team': safe_val(row.get('home_team')),
                'away_score': safe_val(row.get('away_score')),
                'home_score': safe_val(row.get('home_score')),
                'result': safe_val(row.get('result')),
                'total': safe_val(row.get('total')),
                'overtime': safe_val(row.get('overtime')),
                'spread_line': safe_val(row.get('spread_line')),
                'total_line': safe_val(row.get('total_line')),
                'away_moneyline': safe_val(row.get('away_moneyline')),
                'home_moneyline': safe_val(row.get('home_moneyline')),
                'stadium': safe_val(row.get('stadium')),
                'roof': safe_val(row.get('roof')),
                'surface': safe_val(row.get('surface')),
            }
            
            metadata = {k: v for k, v in metadata.items() if v is not None}
            
            content_hash = compute_hash({'sport': 'nfl', 'game_id': str(game_id)})
            
            try:
                await conn.execute(
                    """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                       VALUES ($1, $2, 'nfl_schedule', $3, $4)
                       ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                       DO UPDATE SET metadata = EXCLUDED.metadata""",
                    sport_id, int(season) if season else None, json.dumps(metadata), content_hash
                )
                imported += 1
            except Exception as e:
                logger.debug(f"Error importing schedule: {e}")
        
        gc.collect()
        
    except Exception as e:
        logger.error(f"Error in schedule import: {e}")
        return {"imported": imported, "error": str(e)}
    
    logger.info(f"Imported {imported} NFL schedules")
    return {"imported": imported}


if __name__ == "__main__":
    # For testing
    async def test_import():
        def log_progress(msg):
            print(f"[PROGRESS] {msg}")
        
        result = await import_all_nfl(clear_existing=True, progress_callback=log_progress)
        print(f"Result: {result}")
    
    asyncio.run(test_import())
