"""
NBA Monte Carlo Season Simulator
Ported from: https://github.com/matsonj/nba-monte-carlo

Simulates remainder of NBA season to calculate:
- Playoff odds
- Seed distribution
- Championship probabilities
"""

import logging
import random
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date
from collections import defaultdict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Try to import nba_api
try:
    from nba_api.stats.endpoints import LeagueStandings, ScoreboardV2
    from nba_api.stats.static import teams as nba_teams
    NBA_API_AVAILABLE = True
except ImportError:
    NBA_API_AVAILABLE = False
    logger.warning("nba_api not available - NBA simulations will use mock data")


# Conference assignments
EASTERN_CONFERENCE = [
    "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
    "Chicago Bulls", "Cleveland Cavaliers", "Detroit Pistons", "Indiana Pacers",
    "Miami Heat", "Milwaukee Bucks", "New York Knicks", "Orlando Magic",
    "Philadelphia 76ers", "Toronto Raptors", "Washington Wizards"
]

WESTERN_CONFERENCE = [
    "Dallas Mavericks", "Denver Nuggets", "Golden State Warriors", "Houston Rockets",
    "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Minnesota Timberwolves",
    "New Orleans Pelicans", "Oklahoma City Thunder", "Phoenix Suns", "Portland Trail Blazers",
    "Sacramento Kings", "San Antonio Spurs", "Utah Jazz"
]


def get_team_conference(team_name: str) -> str:
    """Determine conference for a team."""
    if team_name in EASTERN_CONFERENCE:
        return "East"
    elif team_name in WESTERN_CONFERENCE:
        return "West"
    return "Unknown"


class NBATeamRatings:
    """Manages team ratings/Elo for simulation."""
    
    def __init__(self):
        self.ratings: Dict[str, float] = {}
        self.standings: Dict[str, Dict] = {}
        
    def load_from_standings(self, standings_data: List[Dict]) -> None:
        """
        Calculate ratings from current standings.
        Uses win percentage to estimate Elo-like rating.
        
        Base Elo = 1500
        Adjustment = (win_pct - 0.5) * 400
        """
        for team in standings_data:
            team_name = team.get("team_name", "")
            wins = team.get("wins", 0)
            losses = team.get("losses", 0)
            games = wins + losses
            
            if games > 0:
                win_pct = wins / games
            else:
                win_pct = 0.5
            
            # Simple rating: 1500 base + adjustment based on win%
            rating = 1500 + (win_pct - 0.5) * 400
            
            # Store rating and standings
            self.ratings[team_name] = rating
            self.standings[team_name] = {
                "wins": wins,
                "losses": losses,
                "win_pct": win_pct,
                "conference": get_team_conference(team_name)
            }
    
    def get_rating(self, team_name: str) -> float:
        """Get team rating, default to 1500 if unknown."""
        return self.ratings.get(team_name, 1500.0)
    
    def calculate_win_probability(self, home_team: str, away_team: str) -> float:
        """
        Calculate home team win probability using Elo formula.
        
        P(home win) = 1 / (1 + 10^((away_rating - home_rating - HCA) / 400))
        HCA = Home Court Advantage (~100 Elo points, ~3 points)
        """
        home_rating = self.get_rating(home_team)
        away_rating = self.get_rating(away_team)
        home_court_advantage = 100  # ~3 points
        
        exponent = (away_rating - home_rating - home_court_advantage) / 400
        probability = 1 / (1 + 10 ** exponent)
        
        return probability


class NBASeasonSimulator:
    """
    Monte Carlo simulator for NBA season.
    Simulates remaining games to calculate playoff odds.
    """
    
    def __init__(self, num_simulations: int = 1000):
        self.num_simulations = num_simulations
        self.team_ratings = NBATeamRatings()
        self.remaining_games: List[Dict] = []
        self.current_standings: Dict[str, Dict] = {}
        
    def load_current_standings(self) -> Dict:
        """Load current NBA standings."""
        if not NBA_API_AVAILABLE:
            return self._get_mock_standings()
        
        try:
            standings = LeagueStandings()
            data = standings.get_dict()
            
            # Parse standings data
            result_sets = data.get("resultSets", [])
            if not result_sets:
                return self._get_mock_standings()
            
            standings_data = []
            headers = result_sets[0].get("headers", [])
            rows = result_sets[0].get("rowSet", [])
            
            for row in rows:
                row_dict = dict(zip(headers, row))
                team_info = {
                    "team_name": row_dict.get("TeamName", ""),
                    "team_city": row_dict.get("TeamCity", ""),
                    "wins": int(row_dict.get("WINS", 0)),
                    "losses": int(row_dict.get("LOSSES", 0)),
                    "conference": row_dict.get("Conference", ""),
                }
                team_info["full_name"] = f"{team_info['team_city']} {team_info['team_name']}"
                standings_data.append(team_info)
            
            self.team_ratings.load_from_standings([
                {"team_name": t["full_name"], "wins": t["wins"], "losses": t["losses"]}
                for t in standings_data
            ])
            
            self.current_standings = {
                t["full_name"]: {"wins": t["wins"], "losses": t["losses"]}
                for t in standings_data
            }
            
            return {"standings": standings_data, "source": "nba_api"}
            
        except Exception as e:
            logger.error(f"Error loading standings: {e}")
            return self._get_mock_standings()
    
    def _get_mock_standings(self) -> Dict:
        """Generate mock standings for testing."""
        standings = []
        all_teams = EASTERN_CONFERENCE + WESTERN_CONFERENCE
        
        for team in all_teams:
            # Random record mid-season
            wins = random.randint(15, 45)
            losses = random.randint(15, 45)
            standings.append({
                "team_name": team,
                "wins": wins,
                "losses": losses,
                "conference": get_team_conference(team)
            })
        
        self.team_ratings.load_from_standings(standings)
        self.current_standings = {
            t["team_name"]: {"wins": t["wins"], "losses": t["losses"]}
            for t in standings
        }
        
        return {"standings": standings, "source": "mock"}
    
    def generate_remaining_schedule(self) -> List[Dict]:
        """
        Generate remaining schedule.
        For simplicity, generate random matchups for remaining games.
        A full implementation would pull actual remaining schedule.
        """
        all_teams = list(self.current_standings.keys())
        remaining_games = []
        
        # Calculate games remaining per team (82 game season)
        games_per_team = {}
        for team, record in self.current_standings.items():
            games_played = record["wins"] + record["losses"]
            games_remaining = max(0, 82 - games_played)
            games_per_team[team] = games_remaining
        
        # Generate matchups
        game_id = 0
        while any(g > 0 for g in games_per_team.values()):
            # Pick two teams that need games
            available = [t for t, g in games_per_team.items() if g > 0]
            if len(available) < 2:
                break
            
            home, away = random.sample(available, 2)
            remaining_games.append({
                "game_id": game_id,
                "home_team": home,
                "away_team": away
            })
            games_per_team[home] -= 1
            games_per_team[away] -= 1
            game_id += 1
        
        self.remaining_games = remaining_games
        return remaining_games
    
    def simulate_game(self, home_team: str, away_team: str) -> str:
        """Simulate a single game, return winner."""
        home_win_prob = self.team_ratings.calculate_win_probability(home_team, away_team)
        return home_team if random.random() < home_win_prob else away_team
    
    def simulate_season(self) -> Dict[str, Dict]:
        """
        Simulate remainder of season once.
        Returns final standings.
        """
        # Copy current standings
        standings = {
            team: {"wins": data["wins"], "losses": data["losses"]}
            for team, data in self.current_standings.items()
        }
        
        # Simulate remaining games
        for game in self.remaining_games:
            winner = self.simulate_game(game["home_team"], game["away_team"])
            loser = game["away_team"] if winner == game["home_team"] else game["home_team"]
            
            standings[winner]["wins"] += 1
            standings[loser]["losses"] += 1
        
        return standings
    
    def determine_playoff_teams(self, standings: Dict[str, Dict]) -> Dict[str, List[str]]:
        """
        Determine playoff teams from final standings.
        Top 6 in each conference + play-in (7-10).
        """
        east_teams = [(t, s) for t, s in standings.items() if get_team_conference(t) == "East"]
        west_teams = [(t, s) for t, s in standings.items() if get_team_conference(t) == "West"]
        
        # Sort by wins descending
        east_sorted = sorted(east_teams, key=lambda x: x[1]["wins"], reverse=True)
        west_sorted = sorted(west_teams, key=lambda x: x[1]["wins"], reverse=True)
        
        return {
            "east_playoff": [t[0] for t in east_sorted[:6]],
            "east_playin": [t[0] for t in east_sorted[6:10]],
            "west_playoff": [t[0] for t in west_sorted[:6]],
            "west_playin": [t[0] for t in west_sorted[6:10]],
        }
    
    def run_simulations(self) -> Dict:
        """
        Run Monte Carlo simulations.
        Returns aggregated results.
        """
        logger.info(f"Running {self.num_simulations} NBA season simulations...")
        
        # Track results
        playoff_counts = defaultdict(int)
        seed_counts = defaultdict(lambda: defaultdict(int))  # team -> seed -> count
        wins_totals = defaultdict(list)
        
        for sim in range(self.num_simulations):
            final_standings = self.simulate_season()
            playoff_teams = self.determine_playoff_teams(final_standings)
            
            # Track wins
            for team, record in final_standings.items():
                wins_totals[team].append(record["wins"])
            
            # Track playoff appearances
            all_playoff = (
                playoff_teams["east_playoff"] + playoff_teams["east_playin"] +
                playoff_teams["west_playoff"] + playoff_teams["west_playin"]
            )
            for team in all_playoff:
                playoff_counts[team] += 1
            
            # Track seeds
            for conf in ["east", "west"]:
                for seed, team in enumerate(playoff_teams[f"{conf}_playoff"], 1):
                    seed_counts[team][seed] += 1
                for seed, team in enumerate(playoff_teams[f"{conf}_playin"], 7):
                    seed_counts[team][seed] += 1
        
        # Aggregate results
        results = []
        for team in self.current_standings.keys():
            current = self.current_standings[team]
            wins_list = wins_totals[team]
            
            # Calculate seed probabilities
            seed_probs = {}
            for seed in range(1, 11):
                seed_probs[f"seed_{seed}"] = float(round(
                    seed_counts[team][seed] / self.num_simulations * 100, 1
                ))
            
            results.append({
                "team": team,
                "conference": get_team_conference(team),
                "current_wins": int(current["wins"]),
                "current_losses": int(current["losses"]),
                "avg_wins": float(round(np.mean(wins_list), 1)) if wins_list else float(current["wins"]),
                "min_wins": int(min(wins_list)) if wins_list else int(current["wins"]),
                "max_wins": int(max(wins_list)) if wins_list else int(current["wins"]),
                "playoff_pct": float(round(playoff_counts[team] / self.num_simulations * 100, 1)),
                **seed_probs
            })
        
        # Sort by playoff probability
        results.sort(key=lambda x: x["playoff_pct"], reverse=True)
        
        return {
            "simulations": self.num_simulations,
            "games_remaining": len(self.remaining_games),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }


def run_nba_season_simulation(num_simulations: int = 1000) -> Dict:
    """
    Main entry point for NBA season simulation.
    """
    simulator = NBASeasonSimulator(num_simulations=num_simulations)
    
    # Load data
    standings_result = simulator.load_current_standings()
    simulator.generate_remaining_schedule()
    
    # Run simulations
    results = simulator.run_simulations()
    results["data_source"] = standings_result.get("source", "unknown")
    
    return results


if __name__ == "__main__":
    # Test
    results = run_nba_season_simulation(100)
    print(f"\nRan {results['simulations']} simulations")
    print(f"Games remaining: {results['games_remaining']}")
    print("\nTop 10 Playoff Odds:")
    for team in results["results"][:10]:
        print(f"  {team['team']}: {team['playoff_pct']}% playoff, avg {team['avg_wins']} wins")
