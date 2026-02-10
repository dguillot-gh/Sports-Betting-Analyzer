"""
Bet Grader Service
=================
Automated grading of bets by comparing them with the 'results' table.
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
import asyncpg
from src.config import DATABASE_URL

logger = logging.getLogger(__name__)

class BetGrader:
    def __init__(self, db_url: str = DATABASE_URL):
        self.db_url = db_url

    async def grade_all_pending(self):
        """Find and grade all pending bets."""
        logger.info("Starting automated bet grading...")
        conn = await asyncpg.connect(self.db_url)
        try:
            # 1. Fetch pending bets
            bets = await conn.fetch("""
                SELECT * FROM bets 
                WHERE outcome = 'pending' 
                AND (is_mock = TRUE OR created_at < NOW() - INTERVAL '3 hours')
            """)
            
            if not bets:
                logger.info("No pending bets to grade.")
                return 0

            graded_count = 0
            for bet in bets:
                success = await self.grade_bet(conn, bet)
                if success:
                    graded_count += 1
            
            logger.info(f"Finished grading. {graded_count} bets updated.")
            return graded_count
        finally:
            await conn.close()

    async def grade_bet(self, conn, bet):
        """Grade a single bet against the results table."""
        sport = bet['sport'].lower()
        game_id = bet['game_id']
        game_name = bet['game_name'] or ""
        team1 = bet['team1']
        team2 = bet['team2']
        
        # Try to find a matching result
        result = None
        if game_id:
            # Search by game_id in metadata (depends on how it's stored per sport)
            result = await conn.fetchrow("""
                SELECT * FROM results 
                WHERE sport_id = (SELECT id FROM sports WHERE name = $1)
                AND (metadata->>'game_id' = $2 OR metadata->>'gameId' = $2)
            """, sport, game_id)

        if not result and team1 and team2:
            # Search by teams and date proximity
            # This is complex because naming might vary
            # For now, we'll focus on game_id linked bets
            pass

        if not result:
            return False

        # Parse outcome (Logic differs by sport and bet description)
        metadata = json.loads(result['metadata'])
        outcome = self.determine_outcome(bet, metadata)
        
        if outcome and outcome != 'pending':
            # Calculate profit
            from api.bet_tracker_endpoints import calculate_profit
            profit = calculate_profit(bet['stake'], bet['odds'] or 0, outcome)
            
            await conn.execute("""
                UPDATE bets 
                SET outcome = $1, profit = $2, notes = COALESCE(notes, '') || '\n[Auto-Graded]'
                WHERE id = $3
            """, outcome, profit, bet['id'])
            return True
            
        return False

    def determine_outcome(self, bet, result_metadata):
        """
        Heuristic for determining if a bet won.
        Supports: Moneyline
        """
        description = (bet['description'] or "").lower()
        game_name = (bet['game_name'] or "").lower()
        
        # Basic Moneyline logic for NHL/NBA/NFL
        # Usually stored as 'pts' vs 'opponent_pts' or 'goalsFor' etc.
        
        # MoneyPuck (NHL)
        if 'goalsfor' in result_metadata and 'goalsagainst' in result_metadata:
            gf = result_metadata['goalsfor']
            ga = result_metadata['goalsagainst']
            team = (result_metadata.get('team') or "").lower()
            
            # If the bet is on this specific team
            if team in description or team in game_name:
                if gf > ga: return 'win'
                if ga > gf: return 'loss'
                return 'pending' # Might be OT/SO in some datasets

        # NBA (hoopR/sportsdataverse)
        if 'pts' in result_metadata and 'opponent_pts' in result_metadata:
            pts = result_metadata['pts']
            opp_pts = result_metadata['opponent_pts']
            team = (result_metadata.get('team') or "").lower()
            
            if team in description or team in game_name:
                if pts > opp_pts: return 'win'
                if opp_pts > pts: return 'loss'

        # Default: check for 'winner' field if it exists
        winner = (result_metadata.get('winner') or "").lower()
        if winner:
            if winner in description:
                return 'win'
            # This is risky if 'winner' name doesn't match bet description exactly
            
        return 'pending'

async def run_grader():
    grader = BetGrader()
    await grader.grade_all_pending()

if __name__ == "__main__":
    asyncio.run(run_grader())
