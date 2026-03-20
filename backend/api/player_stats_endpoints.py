"""
Player Stats API Endpoints
Provides player stats, game logs, and hit rate data for NBA and NFL
"""

from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional, List, Dict, Any
import pandas as pd
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["player-stats"])

# Data directories
DATA_DIR = Path(__file__).parent.parent / "data"
NBA_DATA_DIR = DATA_DIR / "nba"
NFL_DATA_DIR = DATA_DIR / "nfl"


# ============== NBA Endpoints ==============

@router.get("/nba/players")
async def get_nba_players(
    team: Optional[str] = None,
    limit: int = Query(50, le=200),
    search: Optional[str] = None
):
    """
    Get list of NBA players with season averages.
    """
    try:
        # Try to load player box scores
        box_path = NBA_DATA_DIR / "raw" / "hoopR_player_box_scores.csv"
        if not box_path.exists():
            box_path = NBA_DATA_DIR / "player_box_scores.parquet"
        
        if not box_path.exists():
            # Return demo data if no real data
            return _get_demo_nba_players()
        
        if str(box_path).endswith('.csv'):
            df = pd.read_csv(box_path)
        else:
            df = pd.read_parquet(box_path)
        
        # Identify player and stat columns
        player_col = next((c for c in df.columns if c.lower() in ['athlete_display_name', 'player_name', 'player', 'name']), None)
        team_col = next((c for c in df.columns if c.lower() in ['team_abbreviation', 'team', 'team_name']), None)
        pts_col = next((c for c in df.columns if c.lower() in ['points', 'pts']), None)
        reb_col = next((c for c in df.columns if c.lower() in ['rebounds', 'reb', 'total_rebounds']), None)
        ast_col = next((c for c in df.columns if c.lower() in ['assists', 'ast']), None)
        
        if not player_col:
            return _get_demo_nba_players()
        
        # Aggregate player stats
        agg_dict = {}
        if pts_col:
            agg_dict['ppg'] = (pts_col, 'mean')
            agg_dict['games'] = (pts_col, 'count')
        if reb_col:
            agg_dict['rpg'] = (reb_col, 'mean')
        if ast_col:
            agg_dict['apg'] = (ast_col, 'mean')
        
        if team_col:
            agg_dict['team'] = (team_col, 'first')
        
        if not agg_dict:
            return _get_demo_nba_players()
        
        players = df.groupby(player_col).agg(**agg_dict).reset_index()
        players = players.rename(columns={player_col: 'name'})
        
        # Apply filters
        if search:
            players = players[players['name'].str.contains(search, case=False, na=False)]
        if team and 'team' in players.columns:
            players = players[players['team'] == team]
        
        # Sort by games played and limit
        if 'games' in players.columns:
            players = players.sort_values('games', ascending=False)
        
        players = players.head(limit)
        
        # Clean up for JSON
        for col in ['ppg', 'rpg', 'apg']:
            if col in players.columns:
                players[col] = players[col].round(1)
        
        return players.to_dict(orient='records')
        
    except Exception as e:
        logger.error(f"Error getting NBA players: {e}")
        return _get_demo_nba_players()


@router.get("/nba/player/{player_name}/games")
async def get_nba_player_games(
    player_name: str,
    limit: int = Query(40, le=100)
):
    """
    Get game-by-game stats for an NBA player.
    Returns last N games with all stat columns for hit rate calculation.
    """
    try:
        from urllib.parse import unquote
        player_name = unquote(player_name)
        
        box_path = NBA_DATA_DIR / "raw" / "hoopR_player_box_scores.csv"
        if not box_path.exists():
            box_path = NBA_DATA_DIR / "player_box_scores.parquet"
        
        if not box_path.exists():
            return _get_demo_nba_games(player_name)
        
        if str(box_path).endswith('.csv'):
            df = pd.read_csv(box_path)
        else:
            df = pd.read_parquet(box_path)
        
        # Find player column
        player_col = next((c for c in df.columns if c.lower() in ['athlete_display_name', 'player_name', 'player', 'name']), None)
        if not player_col:
            return _get_demo_nba_games(player_name)
        
        # Filter for player
        player_df = df[df[player_col].str.contains(player_name, case=False, na=False)]
        
        if player_df.empty:
            return {"player": player_name, "games": [], "message": "Player not found"}
        
        # Sort by date if available
        date_col = next((c for c in df.columns if 'date' in c.lower()), None)
        if date_col:
            player_df = player_df.sort_values(date_col, ascending=False)
        
        player_df = player_df.head(limit)
        
        # Map columns to standard names
        games = []
        for _, row in player_df.iterrows():
            game = {}
            
            # Map stat columns
            for col in player_df.columns:
                col_lower = col.lower()
                if 'point' in col_lower or col_lower == 'pts':
                    game['points'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'rebound' in col_lower or col_lower == 'reb':
                    game['rebounds'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'assist' in col_lower or col_lower == 'ast':
                    game['assists'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'three' in col_lower or '3p' in col_lower or 'fg3m' in col_lower:
                    if 'made' in col_lower or col_lower.endswith('m'):
                        game['threes'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'steal' in col_lower or col_lower == 'stl':
                    game['steals'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'block' in col_lower or col_lower == 'blk':
                    game['blocks'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'minute' in col_lower or col_lower == 'min':
                    game['minutes'] = float(row[col]) if pd.notna(row[col]) else 0
                elif 'date' in col_lower:
                    game['date'] = str(row[col]) if pd.notna(row[col]) else ""
                elif 'opponent' in col_lower or col_lower == 'opp':
                    game['opponent'] = str(row[col]) if pd.notna(row[col]) else ""
            
            games.append(game)
        
        return {
            "player": player_name,
            "games": games,
            "total_games": len(games)
        }
        
    except Exception as e:
        logger.error(f"Error getting NBA player games: {e}")
        return _get_demo_nba_games(player_name)


# ============== NFL Endpoints ==============

@router.get("/nfl/players")
async def get_nfl_players(
    position: Optional[str] = None,
    team: Optional[str] = None,
    limit: int = Query(50, le=200),
    search: Optional[str] = None
):
    """
    Get list of NFL players with season stats.
    """
    try:
        # Try weekly stats
        stats_path = NFL_DATA_DIR / "raw" / "player_stats.parquet"
        if not stats_path.exists():
            stats_path = NFL_DATA_DIR / "player_stats.csv"
        
        if not stats_path.exists():
            return _get_demo_nfl_players()
        
        if str(stats_path).endswith('.parquet'):
            df = pd.read_parquet(stats_path)
        else:
            df = pd.read_csv(stats_path)
        
        # Identify columns
        player_col = next((c for c in df.columns if c.lower() in ['player_display_name', 'player_name', 'player', 'name']), None)
        pos_col = next((c for c in df.columns if c.lower() in ['position', 'pos']), None)
        team_col = next((c for c in df.columns if c.lower() in ['recent_team', 'team', 'team_abbr']), None)
        
        if not player_col:
            return _get_demo_nfl_players()
        
        # Aggregate stats
        agg_cols = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'passing_yard' in col_lower:
                agg_cols['pass_yards'] = (col, 'sum')
            elif 'passing_td' in col_lower:
                agg_cols['pass_td'] = (col, 'sum')
            elif 'rushing_yard' in col_lower:
                agg_cols['rush_yards'] = (col, 'sum')
            elif 'rushing_td' in col_lower:
                agg_cols['rush_td'] = (col, 'sum')
            elif 'receiving_yard' in col_lower:
                agg_cols['rec_yards'] = (col, 'sum')
            elif col_lower == 'receptions':
                agg_cols['receptions'] = (col, 'sum')
            elif 'receiving_td' in col_lower:
                agg_cols['rec_td'] = (col, 'sum')
        
        agg_cols['games'] = (player_col, 'count')
        if pos_col:
            agg_cols['position'] = (pos_col, 'first')
        if team_col:
            agg_cols['team'] = (team_col, 'first')
        
        players = df.groupby(player_col).agg(**agg_cols).reset_index()
        players = players.rename(columns={player_col: 'name'})
        
        # Apply filters
        if search:
            players = players[players['name'].str.contains(search, case=False, na=False)]
        if position and 'position' in players.columns:
            players = players[players['position'] == position]
        if team and 'team' in players.columns:
            players = players[players['team'] == team]
        
        players = players.sort_values('games', ascending=False).head(limit)
        
        return players.fillna(0).to_dict(orient='records')
        
    except Exception as e:
        logger.error(f"Error getting NFL players: {e}")
        return _get_demo_nfl_players()


@router.get("/nfl/player/{player_name}/games")
async def get_nfl_player_games(
    player_name: str,
    limit: int = Query(17, le=50)
):
    """
    Get game-by-game stats for an NFL player.
    """
    try:
        from urllib.parse import unquote
        player_name = unquote(player_name)
        
        stats_path = NFL_DATA_DIR / "raw" / "player_stats.parquet"
        if not stats_path.exists():
            return _get_demo_nfl_games(player_name)
        
        df = pd.read_parquet(stats_path)
        
        player_col = next((c for c in df.columns if c.lower() in ['player_display_name', 'player_name', 'player']), None)
        if not player_col:
            return _get_demo_nfl_games(player_name)
        
        player_df = df[df[player_col].str.contains(player_name, case=False, na=False)]
        
        if player_df.empty:
            return {"player": player_name, "games": [], "message": "Player not found"}
        
        # Sort by week
        week_col = next((c for c in df.columns if c.lower() == 'week'), None)
        if week_col:
            player_df = player_df.sort_values(week_col, ascending=False)
        
        player_df = player_df.head(limit)
        
        games = []
        for _, row in player_df.iterrows():
            game = {"week": int(row.get('week', 0)) if 'week' in row else 0}
            
            for col in player_df.columns:
                col_lower = col.lower()
                if 'passing_yard' in col_lower:
                    game['pass_yards'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'passing_td' in col_lower:
                    game['pass_td'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'rushing_yard' in col_lower:
                    game['rush_yards'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'rushing_td' in col_lower:
                    game['rush_td'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'receiving_yard' in col_lower:
                    game['rec_yards'] = int(row[col]) if pd.notna(row[col]) else 0
                elif col_lower == 'receptions':
                    game['receptions'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'completion' in col_lower:
                    game['completions'] = int(row[col]) if pd.notna(row[col]) else 0
                elif 'attempt' in col_lower and 'pass' in col_lower:
                    game['pass_attempts'] = int(row[col]) if pd.notna(row[col]) else 0
            
            games.append(game)
        
        return {
            "player": player_name,
            "games": games,
            "total_games": len(games)
        }
        
    except Exception as e:
        logger.error(f"Error getting NFL player games: {e}")
        return _get_demo_nfl_games(player_name)


# ============== Demo Data Helpers ==============

def _get_demo_nba_players():
    """Return demo NBA player data when real data unavailable."""
    import random
    players = [
        {"name": "LeBron James", "team": "LAL", "position": "SF", "ppg": 25.4, "rpg": 7.8, "apg": 7.1, "games": 40},
        {"name": "Stephen Curry", "team": "GSW", "position": "PG", "ppg": 28.2, "rpg": 4.5, "apg": 5.8, "games": 42},
        {"name": "Kevin Durant", "team": "PHX", "position": "SF", "ppg": 27.1, "rpg": 6.8, "apg": 5.2, "games": 38},
        {"name": "Giannis Antetokounmpo", "team": "MIL", "position": "PF", "ppg": 31.2, "rpg": 11.9, "apg": 5.7, "games": 44},
        {"name": "Luka Doncic", "team": "DAL", "position": "PG", "ppg": 32.4, "rpg": 8.8, "apg": 8.0, "games": 41},
        {"name": "Nikola Jokic", "team": "DEN", "position": "C", "ppg": 26.4, "rpg": 12.4, "apg": 9.0, "games": 45},
        {"name": "Joel Embiid", "team": "PHI", "position": "C", "ppg": 33.1, "rpg": 10.2, "apg": 4.2, "games": 35},
        {"name": "Jayson Tatum", "team": "BOS", "position": "SF", "ppg": 27.0, "rpg": 8.1, "apg": 4.6, "games": 43},
    ]
    return players


def _get_demo_nba_games(player_name: str):
    """Return demo game logs for NBA player."""
    import random
    games = []
    base_pts = random.randint(18, 30)
    base_reb = random.randint(4, 10)
    base_ast = random.randint(3, 8)
    
    for i in range(40):
        games.append({
            "date": f"2024-{random.randint(10,12):02d}-{random.randint(1,28):02d}",
            "points": max(0, base_pts + random.randint(-10, 15)),
            "rebounds": max(0, base_reb + random.randint(-4, 6)),
            "assists": max(0, base_ast + random.randint(-3, 5)),
            "threes": random.randint(0, 6),
            "steals": random.randint(0, 3),
            "blocks": random.randint(0, 3),
            "minutes": random.randint(28, 40)
        })
    
    return {"player": player_name, "games": games, "total_games": len(games), "demo": True}


def _get_demo_nfl_players():
    """Return demo NFL player data."""
    return [
        {"name": "Patrick Mahomes", "team": "KC", "position": "QB", "pass_yards": 4200, "pass_td": 35, "games": 17},
        {"name": "Josh Allen", "team": "BUF", "position": "QB", "pass_yards": 4100, "pass_td": 32, "games": 17},
        {"name": "Christian McCaffrey", "team": "SF", "position": "RB", "rush_yards": 1200, "rush_td": 12, "receptions": 65, "games": 16},
        {"name": "Justin Jefferson", "team": "MIN", "position": "WR", "rec_yards": 1400, "receptions": 105, "rec_td": 9, "games": 17},
        {"name": "Travis Kelce", "team": "KC", "position": "TE", "rec_yards": 1000, "receptions": 90, "rec_td": 8, "games": 17},
        {"name": "Tyreek Hill", "team": "MIA", "position": "WR", "rec_yards": 1600, "receptions": 115, "rec_td": 12, "games": 17},
    ]


def _get_demo_nfl_games(player_name: str):
    """Return demo game logs for NFL player."""
    import random
    games = []
    
    # Assume WR/TE by default
    for week in range(17, 0, -1):
        games.append({
            "week": week,
            "rec_yards": random.randint(40, 140),
            "receptions": random.randint(3, 12),
            "rec_td": random.randint(0, 2),
            "pass_yards": 0,
            "rush_yards": random.randint(0, 20)
        })
    
    return {"player": player_name, "games": games, "total_games": len(games), "demo": True}


# ============== NASCAR Endpoints ==============

NASCAR_DATA_DIR = DATA_DIR / "nascar"

# Teams and their series participation
NASCAR_TEAMS = {
    "Hendrick Motorsports": {"series": ["cup", "xfinity"], "abbr": "HMS"},
    "Joe Gibbs Racing": {"series": ["cup", "xfinity"], "abbr": "JGR"},
    "Team Penske": {"series": ["cup", "xfinity"], "abbr": "Penske"},
    "Stewart-Haas Racing": {"series": ["cup", "xfinity"], "abbr": "SHR"},
    "23XI Racing": {"series": ["cup"], "abbr": "23XI"},
    "Trackhouse Racing": {"series": ["cup"], "abbr": "Trackhouse"},
    "Richard Childress Racing": {"series": ["cup", "xfinity"], "abbr": "RCR"},
    "JR Motorsports": {"series": ["xfinity"], "abbr": "JRM"},
    "Kaulig Racing": {"series": ["cup", "xfinity"], "abbr": "Kaulig"},
    "Roush Fenway Keselowski": {"series": ["cup", "xfinity"], "abbr": "RFK"},
    "Front Row Motorsports": {"series": ["cup", "trucks"], "abbr": "FRM"},
    "Spire Motorsports": {"series": ["cup"], "abbr": "Spire"},
    "Legacy Motor Club": {"series": ["cup"], "abbr": "Legacy"},
    "Wood Brothers Racing": {"series": ["cup"], "abbr": "WBR"},
    "ThorSport Racing": {"series": ["trucks"], "abbr": "ThorSport"},
    "TRICON Garage": {"series": ["trucks"], "abbr": "TRICON"},
    "Hattori Racing": {"series": ["trucks"], "abbr": "HRE"},
}


@router.get("/nascar/teams")
async def get_nascar_teams(request: Request, series: Optional[str] = None):
    """
    Get NASCAR teams, optionally filtered by series.
    Shows which series each team participates in.
    """
    teams = []
    for name, info in NASCAR_TEAMS.items():
        if series is None or series.lower() in info["series"]:
            teams.append({
                "name": name,
                "abbr": info["abbr"],
                "series": info["series"]
            })
    return sorted(teams, key=lambda x: x["name"])


@router.get("/nascar/drivers")
async def get_nascar_drivers(
    team: Optional[str] = None,
    series: Optional[str] = Query("cup", description="cup, xfinity, or trucks"),
    track: Optional[str] = None,
    track_type: Optional[str] = None,
    limit: int = Query(50, le=200),
    search: Optional[str] = None
):
    """
    Get NASCAR drivers with stats, filterable by team, series, track.
    """
    try:
        # Try to load NASCAR data
        data_path = NASCAR_DATA_DIR / "raw" / "nascaR_race_results.csv"
        if not data_path.exists():
            data_path = NASCAR_DATA_DIR / "race_results.parquet"
        
        if not data_path.exists():
            return _get_demo_nascar_drivers(team, series)
        
        if str(data_path).endswith('.csv'):
            df = pd.read_csv(data_path)
        else:
            df = pd.read_parquet(data_path)
        
        # Filter by series if column exists
        series_col = next((c for c in df.columns if c.lower() in ['series', 'series_name']), None)
        if series_col and series:
            series_map = {"cup": "Cup", "xfinity": "Xfinity", "trucks": "Trucks"}
            df = df[df[series_col].str.contains(series_map.get(series.lower(), series), case=False, na=False)]
        
        # Filter by track type
        track_type_col = next((c for c in df.columns if c.lower() == 'track_type'), None)
        if track_type_col and track_type:
            df = df[df[track_type_col].str.contains(track_type, case=False, na=False)]
        
        # Filter by track
        track_col = next((c for c in df.columns if c.lower() in ['track', 'track_name']), None)
        if track_col and track:
            df = df[df[track_col].str.contains(track, case=False, na=False)]
        
        if df.empty:
            return _get_demo_nascar_drivers(team, series)
        
        # Find columns
        driver_col = next((c for c in df.columns if c.lower() in ['driver', 'driver_name']), None)
        team_col = next((c for c in df.columns if c.lower() in ['team', 'team_name', 'owner']), None)
        finish_col = next((c for c in df.columns if c.lower() in ['finish', 'finish_position', 'pos']), None)
        start_col = next((c for c in df.columns if c.lower() in ['start', 'start_position', 'qualifying_position']), None)
        laps_led_col = next((c for c in df.columns if c.lower() in ['laps_led', 'led']), None)
        
        if not driver_col:
            return _get_demo_nascar_drivers(team, series)
        
        # Aggregate driver stats
        agg_dict = {
            'races': (driver_col, 'count'),
        }
        if finish_col:
            agg_dict['avg_finish'] = (finish_col, 'mean')
        if start_col:
            agg_dict['avg_start'] = (start_col, 'mean')
        if laps_led_col:
            agg_dict['total_laps_led'] = (laps_led_col, 'sum')
        if team_col:
            agg_dict['team'] = (team_col, 'first')
        
        # Calculate wins, top5, top10
        if finish_col:
            df['is_win'] = df[finish_col] == 1
            df['is_top5'] = df[finish_col] <= 5
            df['is_top10'] = df[finish_col] <= 10
            agg_dict['wins'] = ('is_win', 'sum')
            agg_dict['top5'] = ('is_top5', 'sum')
            agg_dict['top10'] = ('is_top10', 'sum')
        
        drivers = df.groupby(driver_col).agg(**agg_dict).reset_index()
        drivers = drivers.rename(columns={driver_col: 'name'})
        
        # Filter by team
        if team and 'team' in drivers.columns:
            drivers = drivers[drivers['team'].str.contains(team, case=False, na=False)]
        
        # Filter by search
        if search:
            drivers = drivers[drivers['name'].str.contains(search, case=False, na=False)]
        
        # Sort and limit
        drivers = drivers.sort_values('races', ascending=False).head(limit)
        
        # Round averages
        if 'avg_finish' in drivers.columns:
            drivers['avg_finish'] = drivers['avg_finish'].round(1)
        if 'avg_start' in drivers.columns:
            drivers['avg_start'] = drivers['avg_start'].round(1)
        
        # Calculate hit rates
        drivers['top5_pct'] = ((drivers['top5'] / drivers['races']) * 100).round(1)
        drivers['top10_pct'] = ((drivers['top10'] / drivers['races']) * 100).round(1)
        drivers['win_pct'] = ((drivers['wins'] / drivers['races']) * 100).round(1)
        
        return drivers.fillna(0).to_dict(orient='records')
        
    except Exception as e:
        logger.error(f"Error getting NASCAR drivers: {e}")
        return _get_demo_nascar_drivers(team, series)


@router.get("/nascar/team/{team_name}/stats")
async def get_nascar_team_stats(
    team_name: str,
    series: Optional[str] = Query("cup"),
    track: Optional[str] = None,
    track_type: Optional[str] = None
):
    """
    Get team-level stats, optionally filtered by track.
    Shows overall team performance and individual driver breakdown.
    """
    from urllib.parse import unquote
    team_name = unquote(team_name)
    
    # Get all drivers for this team
    drivers = await get_nascar_drivers(
        team=team_name, 
        series=series, 
        track=track, 
        track_type=track_type,
        limit=20
    )
    
    if not drivers:
        return {
            "team": team_name,
            "series": series,
            "drivers": [],
            "team_stats": {}
        }
    
    # Aggregate team stats
    total_races = sum(d.get('races', 0) for d in drivers)
    total_wins = sum(d.get('wins', 0) for d in drivers)
    total_top5 = sum(d.get('top5', 0) for d in drivers)
    total_top10 = sum(d.get('top10', 0) for d in drivers)
    
    team_stats = {
        "total_races": total_races,
        "total_wins": total_wins,
        "total_top5": total_top5,
        "total_top10": total_top10,
        "win_pct": round(total_wins / total_races * 100, 1) if total_races > 0 else 0,
        "top5_pct": round(total_top5 / total_races * 100, 1) if total_races > 0 else 0,
        "top10_pct": round(total_top10 / total_races * 100, 1) if total_races > 0 else 0,
    }
    
    return {
        "team": team_name,
        "series": series,
        "track": track,
        "track_type": track_type,
        "team_stats": team_stats,
        "drivers": sorted(drivers, key=lambda x: x.get('avg_finish', 99))
    }


@router.get("/nascar/driver/{driver_name}/races")
async def get_nascar_driver_races(
    driver_name: str,
    series: Optional[str] = Query("cup"),
    track: Optional[str] = None,
    track_type: Optional[str] = None,
    limit: int = Query(36, le=100)
):
    """
    Get race-by-race results for a NASCAR driver.
    Used for hit rate calculations (Top 5, Top 10, etc.)
    """
    try:
        from urllib.parse import unquote
        driver_name = unquote(driver_name)
        
        data_path = NASCAR_DATA_DIR / "raw" / "nascaR_race_results.csv"
        if not data_path.exists():
            return _get_demo_nascar_races(driver_name)
        
        df = pd.read_csv(data_path)
        
        # Filter by series
        series_col = next((c for c in df.columns if c.lower() in ['series', 'series_name']), None)
        if series_col and series:
            series_map = {"cup": "Cup", "xfinity": "Xfinity", "trucks": "Trucks"}
            df = df[df[series_col].str.contains(series_map.get(series.lower(), series), case=False, na=False)]
        
        # Filter by track type
        track_type_col = next((c for c in df.columns if c.lower() == 'track_type'), None)
        if track_type_col and track_type:
            df = df[df[track_type_col].str.contains(track_type, case=False, na=False)]
        
        # Filter by track
        track_col = next((c for c in df.columns if c.lower() in ['track', 'track_name']), None)
        if track_col and track:
            df = df[df[track_col].str.contains(track, case=False, na=False)]
        
        # Filter by driver
        driver_col = next((c for c in df.columns if c.lower() in ['driver', 'driver_name']), None)
        if not driver_col:
            return _get_demo_nascar_races(driver_name)
        
        driver_df = df[df[driver_col].str.contains(driver_name, case=False, na=False)]
        
        if driver_df.empty:
            return {"driver": driver_name, "races": [], "message": "Driver not found"}
        
        # Sort by date/race
        date_col = next((c for c in df.columns if 'date' in c.lower()), None)
        if date_col:
            driver_df = driver_df.sort_values(date_col, ascending=False)
        
        driver_df = driver_df.head(limit)
        
        # Extract race data
        races = []
        for _, row in driver_df.iterrows():
            race = {}
            
            for col in driver_df.columns:
                col_lower = col.lower()
                if col_lower in ['finish', 'finish_position', 'pos']:
                    race['finish'] = int(row[col]) if pd.notna(row[col]) else 0
                elif col_lower in ['start', 'start_position']:
                    race['start'] = int(row[col]) if pd.notna(row[col]) else 0
                elif col_lower in ['laps_led', 'led']:
                    race['laps_led'] = int(row[col]) if pd.notna(row[col]) else 0
                elif col_lower in ['track', 'track_name']:
                    race['track'] = str(row[col]) if pd.notna(row[col]) else ""
                elif col_lower == 'track_type':
                    race['track_type'] = str(row[col]) if pd.notna(row[col]) else ""
                elif 'date' in col_lower:
                    race['date'] = str(row[col]) if pd.notna(row[col]) else ""
                elif col_lower == 'status':
                    race['status'] = str(row[col]) if pd.notna(row[col]) else ""
            
            races.append(race)
        
        return {
            "driver": driver_name,
            "series": series,
            "track": track,
            "track_type": track_type,
            "races": races,
            "total_races": len(races)
        }
        
    except Exception as e:
        logger.error(f"Error getting NASCAR driver races: {e}")
        return _get_demo_nascar_races(driver_name)


@router.get("/nascar/tracks")
async def get_nascar_tracks(request: Request):
    """Get list of NASCAR tracks with their types."""
    return [
        {"name": "Daytona International Speedway", "type": "superspeedway"},
        {"name": "Talladega Superspeedway", "type": "superspeedway"},
        {"name": "Charlotte Motor Speedway", "type": "intermediate"},
        {"name": "Texas Motor Speedway", "type": "intermediate"},
        {"name": "Atlanta Motor Speedway", "type": "intermediate"},
        {"name": "Kansas Speedway", "type": "intermediate"},
        {"name": "Las Vegas Motor Speedway", "type": "intermediate"},
        {"name": "Michigan International Speedway", "type": "intermediate"},
        {"name": "Bristol Motor Speedway", "type": "short"},
        {"name": "Martinsville Speedway", "type": "short"},
        {"name": "Richmond Raceway", "type": "short"},
        {"name": "Phoenix Raceway", "type": "short"},
        {"name": "Nashville Superspeedway", "type": "intermediate"},
        {"name": "Watkins Glen International", "type": "road"},
        {"name": "Sonoma Raceway", "type": "road"},
        {"name": "Road America", "type": "road"},
        {"name": "Circuit of the Americas", "type": "road"},
        {"name": "Indianapolis Motor Speedway", "type": "road"},
        {"name": "Chicago Street Course", "type": "street"},
        {"name": "Darlington Raceway", "type": "intermediate"},
        {"name": "Pocono Raceway", "type": "intermediate"},
        {"name": "New Hampshire Motor Speedway", "type": "short"},
        {"name": "Iowa Speedway", "type": "short"},
        {"name": "Dover Motor Speedway", "type": "intermediate"},
    ]


def _get_demo_nascar_drivers(team: Optional[str] = None, series: Optional[str] = None):
    """Return demo NASCAR driver data."""
    import random
    
    drivers = [
        {"name": "Kyle Larson", "team": "Hendrick Motorsports", "avg_finish": 8.2, "races": 36, "wins": 6, "top5": 16, "top10": 24},
        {"name": "William Byron", "team": "Hendrick Motorsports", "avg_finish": 10.1, "races": 36, "wins": 4, "top5": 12, "top10": 20},
        {"name": "Chase Elliott", "team": "Hendrick Motorsports", "avg_finish": 11.5, "races": 36, "wins": 2, "top5": 10, "top10": 18},
        {"name": "Alex Bowman", "team": "Hendrick Motorsports", "avg_finish": 14.2, "races": 36, "wins": 1, "top5": 6, "top10": 14},
        {"name": "Martin Truex Jr", "team": "Joe Gibbs Racing", "avg_finish": 9.8, "races": 36, "wins": 3, "top5": 14, "top10": 22},
        {"name": "Christopher Bell", "team": "Joe Gibbs Racing", "avg_finish": 10.5, "races": 36, "wins": 3, "top5": 11, "top10": 19},
        {"name": "Denny Hamlin", "team": "Joe Gibbs Racing", "avg_finish": 11.2, "races": 36, "wins": 2, "top5": 9, "top10": 17},
        {"name": "Ty Gibbs", "team": "Joe Gibbs Racing", "avg_finish": 15.3, "races": 36, "wins": 0, "top5": 4, "top10": 10},
        {"name": "Joey Logano", "team": "Team Penske", "avg_finish": 12.1, "races": 36, "wins": 2, "top5": 8, "top10": 16},
        {"name": "Ryan Blaney", "team": "Team Penske", "avg_finish": 11.8, "races": 36, "wins": 3, "top5": 10, "top10": 18},
        {"name": "Austin Cindric", "team": "Team Penske", "avg_finish": 16.5, "races": 36, "wins": 0, "top5": 3, "top10": 8},
        {"name": "Tyler Reddick", "team": "23XI Racing", "avg_finish": 13.2, "races": 36, "wins": 1, "top5": 7, "top10": 14},
        {"name": "Bubba Wallace", "team": "23XI Racing", "avg_finish": 18.1, "races": 36, "wins": 0, "top5": 2, "top10": 6},
    ]
    
    for d in drivers:
        d['top5_pct'] = round(d['top5'] / d['races'] * 100, 1)
        d['top10_pct'] = round(d['top10'] / d['races'] * 100, 1)
        d['win_pct'] = round(d['wins'] / d['races'] * 100, 1)
        d['total_laps_led'] = random.randint(50, 500)
        d['avg_start'] = round(d['avg_finish'] - random.uniform(-3, 5), 1)
    
    if team:
        drivers = [d for d in drivers if team.lower() in d['team'].lower()]
    
    return drivers


def _get_demo_nascar_races(driver_name: str):
    """Return demo race results for NASCAR driver."""
    import random
    
    tracks = [
        ("Daytona", "superspeedway"), ("Talladega", "superspeedway"),
        ("Charlotte", "intermediate"), ("Texas", "intermediate"),
        ("Bristol", "short"), ("Martinsville", "short"),
        ("Watkins Glen", "road"), ("Sonoma", "road"),
    ]
    
    races = []
    for i in range(36):
        track, track_type = random.choice(tracks)
        finish = random.randint(1, 38)
        races.append({
            "date": f"2024-{random.randint(2,11):02d}-{random.randint(1,28):02d}",
            "track": track,
            "track_type": track_type,
            "start": random.randint(1, 35),
            "finish": finish,
            "laps_led": random.randint(0, 50) if finish <= 10 else 0,
            "status": "Running" if finish <= 30 else random.choice(["Engine", "Crash", "Running"])
        })
    
    return {"driver": driver_name, "races": races, "total_races": len(races), "demo": True}
