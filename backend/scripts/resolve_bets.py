"""
Resolve Bets Script
==================
Automatically resolves pending mock bets by fetching game results and determining outcomes.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import asyncpg

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting')


async def get_pending_bets() -> List[Dict[str, Any]]:
    """Fetch all pending mock bets that have a game_id and bet_metadata."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch("""
            SELECT id, game_id, bet_metadata, sport, stake, odds
            FROM bets 
            WHERE outcome = 'pending' 
              AND is_mock = TRUE 
              AND game_id IS NOT NULL
              AND bet_metadata IS NOT NULL
            ORDER BY created_at DESC
        """)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def fetch_game_result(game_id: str, sport: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the final score for a game.
    Returns dict with 'home_score', 'away_score', 'home_team', 'away_team', 'status'
    """
    try:
        # Try to use sbrscrape for NBA/NFL
        if sport in ['nba', 'nfl', 'ncaab', 'ncaaf']:
            from sbrscrape import Scoreboard
            
            # Parse date from game_id if possible, or use yesterday
            game_date = datetime.utcnow().date() - timedelta(days=1)
            
            sb = Scoreboard(sport=sport.upper() if sport in ['nba', 'nfl'] else sport)
            games = sb.games if hasattr(sb, 'games') else []
            
            for game in games:
                gid = getattr(game, 'game_id', None) or f"{getattr(game, 'away_team', '')}:{getattr(game, 'home_team', '')}"
                if gid == game_id or game_id in str(gid):
                    if getattr(game, 'is_final', False) or getattr(game, 'status', '') == 'Final':
                        return {
                            'home_team': getattr(game, 'home_team', ''),
                            'away_team': getattr(game, 'away_team', ''),
                            'home_score': getattr(game, 'home_score', 0),
                            'away_score': getattr(game, 'away_score', 0),
                            'status': 'final'
                        }
        
        logger.warning(f"Could not find result for game {game_id} ({sport})")
        return None
    except Exception as e:
        logger.error(f"Error fetching game result for {game_id}: {e}")
        return None


def evaluate_bet(metadata: Dict[str, Any], result: Dict[str, Any]) -> str:
    """
    Evaluate bet outcome based on metadata and game result.
    Returns: 'win', 'loss', or 'push'
    """
    bet_type = metadata.get('type', 'ml')
    home_score = result.get('home_score', 0)
    away_score = result.get('away_score', 0)
    bet_team = metadata.get('team', '')
    bet_value = metadata.get('value')
    total_points = home_score + away_score
    
    # Determine which team won
    home_team = result.get('home_team', '')
    away_team = result.get('away_team', '')
    home_won = home_score > away_score
    margin = home_score - away_score
    
    if bet_type == 'ml':
        # Moneyline bet
        if bet_team.lower() in home_team.lower():
            return 'win' if home_won else 'loss'
        elif bet_team.lower() in away_team.lower():
            return 'win' if not home_won else 'loss'
        else:
            logger.warning(f"Could not match team '{bet_team}' to game teams")
            return 'pending'
    
    elif bet_type == 'spread':
        # Spread bet
        spread = float(bet_value) if bet_value else 0
        if bet_team.lower() in home_team.lower():
            # Bet on home team with spread
            covered = margin + spread > 0
            push = margin + spread == 0
        else:
            # Bet on away team with spread
            covered = -margin + spread > 0
            push = -margin + spread == 0
        
        if push:
            return 'push'
        return 'win' if covered else 'loss'
    
    elif bet_type == 'total':
        # Over/Under bet
        line = float(bet_value) if bet_value else 0
        side = metadata.get('side', 'over')
        
        if total_points == line:
            return 'push'
        elif side == 'over':
            return 'win' if total_points > line else 'loss'
        else:  # under
            return 'win' if total_points < line else 'loss'
    
    return 'pending'


async def update_bet_outcome(bet_id: int, outcome: str, profit: float):
    """Update the bet outcome in the database."""
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            UPDATE bets 
            SET outcome = $1, profit = $2, settled_at = NOW()
            WHERE id = $3
        """, outcome, profit, bet_id)
        logger.info(f"Updated bet {bet_id}: outcome={outcome}, profit={profit:.2f}")
    finally:
        await conn.close()


def calculate_profit(stake: float, odds: int, outcome: str) -> float:
    """Calculate profit based on outcome."""
    if outcome == 'win':
        if odds > 0:
            return stake * odds / 100
        else:
            return stake * 100 / abs(odds)
    elif outcome == 'loss':
        return -stake
    else:  # push
        return 0


async def resolve_all_pending_bets() -> Dict[str, Any]:
    """
    Main function to resolve all pending mock bets.
    Returns a summary of the resolution process.
    """
    results = {
        'total': 0,
        'resolved': 0,
        'wins': 0,
        'losses': 0,
        'pushes': 0,
        'skipped': 0,
        'errors': 0,
        'details': []
    }
    
    pending_bets = await get_pending_bets()
    results['total'] = len(pending_bets)
    
    logger.info(f"Found {len(pending_bets)} pending bets to resolve")
    
    for bet in pending_bets:
        bet_id = bet['id']
        game_id = bet['game_id']
        sport = bet.get('sport', 'nba')
        stake = float(bet.get('stake', 0))
        odds = bet.get('odds', -110)
        
        # Parse metadata
        try:
            if isinstance(bet['bet_metadata'], str):
                metadata = json.loads(bet['bet_metadata'])
            else:
                metadata = bet['bet_metadata']
        except (json.JSONDecodeError, TypeError):
            logger.error(f"Invalid metadata for bet {bet_id}")
            results['errors'] += 1
            continue
        
        if not metadata:
            results['skipped'] += 1
            results['details'].append({'id': bet_id, 'status': 'skipped', 'reason': 'No metadata'})
            continue
        
        # Fetch game result
        result = await fetch_game_result(game_id, sport)
        
        if not result or result.get('status') != 'final':
            results['skipped'] += 1
            results['details'].append({'id': bet_id, 'status': 'skipped', 'reason': 'Game not final'})
            continue
        
        # Evaluate outcome
        outcome = evaluate_bet(metadata, result)
        
        if outcome == 'pending':
            results['skipped'] += 1
            results['details'].append({'id': bet_id, 'status': 'skipped', 'reason': 'Could not evaluate'})
            continue
        
        # Calculate profit
        profit = calculate_profit(stake, odds, outcome)
        
        # Update database
        try:
            await update_bet_outcome(bet_id, outcome, profit)
            results['resolved'] += 1
            
            if outcome == 'win':
                results['wins'] += 1
            elif outcome == 'loss':
                results['losses'] += 1
            else:
                results['pushes'] += 1
            
            results['details'].append({
                'id': bet_id,
                'status': 'resolved',
                'outcome': outcome,
                'profit': profit
            })
        except Exception as e:
            logger.error(f"Error updating bet {bet_id}: {e}")
            results['errors'] += 1
    
    return results


if __name__ == "__main__":
    import sys
    
    print("🎯 Bet Resolution Script")
    print("=" * 40)
    
    results = asyncio.run(resolve_all_pending_bets())
    
    print(f"\n📊 Results:")
    print(f"  Total pending: {results['total']}")
    print(f"  Resolved: {results['resolved']}")
    print(f"  - Wins: {results['wins']}")
    print(f"  - Losses: {results['losses']}")
    print(f"  - Pushes: {results['pushes']}")
    print(f"  Skipped: {results['skipped']}")
    print(f"  Errors: {results['errors']}")
    
    sys.exit(0 if results['errors'] == 0 else 1)
