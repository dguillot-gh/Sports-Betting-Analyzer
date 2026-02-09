"""
CLV Calculator Service
======================
Captures closing lines for bets and calculates CLV Edge.
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
import asyncpg
from src.config import DATABASE_URL
from src.odds_cache import OddsCacheService

logger = logging.getLogger(__name__)

class CLVCalculator:
    def __init__(self, db_url: str = DATABASE_URL):
        self.db_url = db_url
        self.cache_service = OddsCacheService()

    async def snapshot_closing_lines(self):
        """
        Identify bets whose games are about to start or have just started,
        and capture their closing lines from the cache.
        """
        logger.info("Snapshoting closing lines for pending bets...")
        conn = await asyncpg.connect(self.db_url)
        try:
            # 1. Find bets needing closing lines
            # Game starts between 1 hour ago and 30 mins from now
            # and closing_odds is still NULL
            bets = await conn.fetch("""
                SELECT * FROM bets 
                WHERE closing_odds IS NULL 
                AND game_date IS NOT NULL
                AND game_date BETWEEN NOW() - INTERVAL '4 hours' AND NOW() + INTERVAL '30 minutes'
            """)
            
            if not bets:
                logger.debug("No bets needing closing line snapshots right now.")
                return 0

            updated_count = 0
            for bet in bets:
                success = await self._capture_line_for_bet(conn, bet)
                if success:
                    updated_count += 1
            
            logger.info(f"Captured closing lines for {updated_count} bets.")
            return updated_count
        finally:
            await conn.close()

    async def _capture_line_for_bet(self, conn, bet):
        sport = bet['sport'].lower()
        game_id = bet['game_id']
        sportsbook = bet['sportsbook'].lower()
        
        if not game_id:
            return False

        # Get the latest cached odds for this game
        # We'll use the OddsCacheService which we already researched
        cached_games = await self.cache_service.get_cached_games(sport, include_expired=True)
        game_data = next((g for g in cached_games if g.get('id') == game_id), None)
        
        if not game_data:
            return False

        odds_data = game_data.get('odds_data', {})
        # Find the odds for the specific sportsbook
        # Structure is usually: { 'fanduel': { 'home_ml': -110, ... }, ... }
        book_odds = odds_data.get(sportsbook) or odds_data.get('fanduel') # Fallback to FD if specific book missing
        
        if not book_odds:
            return False

        # Determine the closing odds based on the bet description
        closing_odds = self._extract_relevant_odds(bet, book_odds)
        
        if closing_odds:
            # Calculate CLV Percent
            placed_odds = bet['odds']
            clv_percent = self.calculate_clv(placed_odds, closing_odds)
            
            await conn.execute("""
                UPDATE bets 
                SET closing_odds = $1, 
                    closing_odds_source = $2, 
                    closing_odds_captured_at = NOW(),
                    clv_percent = $3
                WHERE id = $4
            """, closing_odds, sportsbook, clv_percent, bet['id'])
            return True
            
        return False

    def _extract_relevant_odds(self, bet, book_odds):
        """Extract the specific odds (ML, Spread, etc) that match the bet."""
        desc = (bet['description'] or "").lower()
        game_name = (bet['game_name'] or "").lower()
        
        # Moneyline
        if 'home_moneyline' in book_odds and 'away_moneyline' in book_odds:
            # We need to know if the bet was on the home or away team
            # This is a heuristic based on descriptions
            if "home" in desc or (bet['team1'] and bet['team1'].lower() in desc):
                 return book_odds.get('home_moneyline')
            if "away" in desc or (bet['team2'] and bet['team2'].lower() in desc):
                 return book_odds.get('away_moneyline')
                 
        # Spread
        if 'spread' in book_odds:
            return book_odds.get('spread_odds') # This would need more complex logic for spread value vs odds
            
        return None

    def calculate_clv(self, placed_american, closing_american):
        """Calculate CLV % based on implied probabilities."""
        def implied_prob(american):
            if american > 0:
                return 100 / (american + 100)
            else:
                return abs(american) / (abs(american) + 100)
        
        prob_placed = implied_prob(placed_american)
        prob_closing = implied_prob(closing_american)
        
        if prob_placed == 0: return 0
        
        # Market Edge = (Prob Closing / Prob Placed) - 1
        # E.g. Placed at +100 (50%), Closed at -110 (52.4%)
        # CLV = (52.4 / 50) - 1 = +4.8%
        return round(((prob_closing / prob_placed) - 1) * 100, 2)

async def run_clv():
    calc = CLVCalculator()
    await calc.snapshot_closing_lines()

if __name__ == "__main__":
    asyncio.run(run_clv())
