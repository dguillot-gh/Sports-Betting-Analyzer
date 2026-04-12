"""
MLB Live Odds Integration
Fetches live betting lines from sportsbooks using sbrscrape
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

logger = logging.getLogger(__name__)

SPORTSBOOKS = [
    "fanduel",
    "draftkings",
    "betmgm",
    "pointsbet",
    "caesars",
    "wynn",
    "bet_rivers_ny"
]


async def get_todays_mlb_odds(sportsbook: str = "fanduel") -> Dict[str, Any]:
    """
    Fetch today's MLB odds from the specified sportsbook via sbrscrape.
    """
    try:
        from sbrscrape import Scoreboard
    except ImportError:
        logger.error("sbrscrape not installed. Run: pip install sbrscrape")
        return {"error": "sbrscrape not installed", "games": []}

    try:
        # Use "Sports Date" (UTC - 6 hours) so late games count as "today"
        today = (datetime.utcnow() - timedelta(hours=6)).date()
        sb = Scoreboard(sport="MLB", date=today)

        if not hasattr(sb, "games") or not sb.games:
            return {
                "date": str(today),
                "sportsbook": sportsbook,
                "games": [],
                "message": "No MLB games found for today"
            }

        games = []
        for game in sb.games:
            try:
                game_data = {
                    "home_team": game.get("home_team", "Unknown"),
                    "away_team": game.get("away_team", "Unknown"),
                    "home_score": game.get("home_score"),
                    "away_score": game.get("away_score"),
                    "game_time": str(game.get("game_time", "")),
                    "status": game.get("status", "scheduled"),
                }

                if "total" in game and sportsbook in game["total"]:
                    game_data["over_under"] = game["total"][sportsbook]

                if "away_spread" in game and sportsbook in game["away_spread"]:
                    game_data["spread"] = game["away_spread"][sportsbook]

                if "home_ml" in game and sportsbook in game["home_ml"]:
                    game_data["home_moneyline"] = game["home_ml"][sportsbook]

                if "away_ml" in game and sportsbook in game["away_ml"]:
                    game_data["away_moneyline"] = game["away_ml"][sportsbook]

                games.append(game_data)

            except Exception as e:
                logger.warning(f"Error parsing MLB game: {e}")
                continue

        return {
            "date": str(today),
            "sportsbook": sportsbook,
            "games": games,
            "count": len(games)
        }

    except Exception as e:
        logger.error(f"Error fetching MLB odds: {e}")
        return {
            "error": str(e),
            "games": [],
            "sportsbook": sportsbook
        }
