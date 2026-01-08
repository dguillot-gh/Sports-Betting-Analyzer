"""
Bet Tracker API Endpoints
=========================
Track bets with W/L/CashOut toggle, parlay support, and game linking.
"""

import asyncio
import json
import logging
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query

import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bets", tags=["Bet Tracker"])

# Use environment variable with fallback for local development
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting")

# ==================== Pydantic Models ====================

class BetLeg(BaseModel):
    """A leg in a parlay bet."""
    game_id: Optional[str] = None
    description: str  # "Chiefs ML" or "Lakers -5.5"
    odds: int


class CreateBetRequest(BaseModel):
    """Request to create a new bet."""
    sport: str = Field(..., description="nfl, nba, nascar")
    bet_type: str = Field("single", description="single or parlay")
    sportsbook: str = Field("fanduel", description="Sportsbook name")
    stake: float = Field(..., gt=0, description="Amount wagered")
    odds: Optional[int] = Field(None, description="American odds (for singles)")
    game_id: Optional[str] = Field(None, description="Linked game ID from cache")
    description: Optional[str] = Field(None, description="Bet description")
    legs: Optional[List[BetLeg]] = Field(None, description="Parlay legs")
    notes: Optional[str] = None


class UpdateOutcomeRequest(BaseModel):
    """Request to update bet outcome."""
    outcome: str = Field(..., description="win, loss, cashout, pending")
    cashout_amount: Optional[float] = Field(None, description="Cash out amount if applicable")


class BetResponse(BaseModel):
    """Bet response with calculated fields."""
    id: int
    created_at: str
    sport: str
    bet_type: str
    sportsbook: str
    stake: float
    odds: Optional[int]
    potential_payout: Optional[float]
    outcome: str
    cashout_amount: Optional[float]
    profit: Optional[float]
    game_id: Optional[str]
    description: Optional[str]
    notes: Optional[str]
    legs: Optional[List[dict]] = None


# ==================== SQL ====================

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS bets (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    sport VARCHAR(20),
    bet_type VARCHAR(20) DEFAULT 'single',
    sportsbook VARCHAR(50),
    stake DECIMAL(10,2) NOT NULL,
    odds INT,
    potential_payout DECIMAL(10,2),
    outcome VARCHAR(10) DEFAULT 'pending',
    cashout_amount DECIMAL(10,2),
    profit DECIMAL(10,2),
    game_id VARCHAR(100),
    description VARCHAR(200),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS bet_legs (
    id SERIAL PRIMARY KEY,
    bet_id INT REFERENCES bets(id) ON DELETE CASCADE,
    game_id VARCHAR(100),
    description VARCHAR(200),
    odds INT,
    outcome VARCHAR(10) DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS idx_bets_sport ON bets(sport);
CREATE INDEX IF NOT EXISTS idx_bets_outcome ON bets(outcome);
CREATE INDEX IF NOT EXISTS idx_bets_created ON bets(created_at);
"""

_tables_initialized = False


async def ensure_tables():
    """Create tables if they don't exist."""
    global _tables_initialized
    if _tables_initialized:
        return
    
    try:
        import asyncpg
        logger.info(f"Connecting to database: {DATABASE_URL[:50]}...")
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(CREATE_TABLES_SQL)
        await conn.close()
        _tables_initialized = True
        logger.info("Bet tracker tables initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize bet tables: {e}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")


# ==================== Helper Functions ====================

def calculate_potential_payout(stake: float, odds: int) -> float:
    """Calculate potential payout from American odds."""
    if odds > 0:
        return stake + (stake * odds / 100)
    else:
        return stake + (stake * 100 / abs(odds))


def calculate_profit(stake: float, odds: int, outcome: str, cashout_amount: Optional[float] = None) -> float:
    """Calculate profit based on outcome."""
    if outcome == "win":
        if odds > 0:
            return stake * odds / 100
        else:
            return stake * 100 / abs(odds)
    elif outcome == "loss":
        return -stake
    elif outcome == "cashout" and cashout_amount is not None:
        return cashout_amount - stake
    return 0


def calculate_parlay_odds(legs: List[BetLeg]) -> int:
    """Calculate combined parlay odds from legs."""
    if not legs:
        return 0
    
    decimal_odds = 1.0
    for leg in legs:
        if leg.odds > 0:
            decimal_odds *= (leg.odds / 100) + 1
        else:
            decimal_odds *= (100 / abs(leg.odds)) + 1
    
    # Convert back to American
    if decimal_odds >= 2:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


# ==================== Endpoints ====================

@router.post("/init")
async def init_bet_tables():
    """Initialize bet tracker tables."""
    await ensure_tables()
    return {"status": "ok", "message": "Bet tracker tables ready"}


@router.get("/health")
async def bet_tracker_health():
    """Check bet tracker database connectivity."""
    try:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        result = await conn.fetchval("SELECT COUNT(*) FROM bets")
        await conn.close()
        return {
            "status": "healthy",
            "database": "connected",
            "bet_count": result,
            "database_url": DATABASE_URL[:50] + "..."
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
            "database_url": DATABASE_URL[:50] + "..."
        }


@router.post("", response_model=BetResponse)
async def create_bet(request: CreateBetRequest):
    """Create a new bet."""
    import asyncpg
    
    await ensure_tables()
    
    # Calculate odds for parlays
    if request.bet_type == "parlay" and request.legs:
        combined_odds = calculate_parlay_odds(request.legs)
    else:
        combined_odds = request.odds or 0
    
    potential_payout = calculate_potential_payout(request.stake, combined_odds) if combined_odds else None
    
    # Build description
    if request.description:
        description = request.description
    elif request.bet_type == "parlay" and request.legs:
        description = f"{len(request.legs)}-leg parlay"
    else:
        description = None
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Insert bet
        row = await conn.fetchrow("""
            INSERT INTO bets (sport, bet_type, sportsbook, stake, odds, potential_payout, game_id, description, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
        """, request.sport, request.bet_type, request.sportsbook, 
            request.stake, combined_odds, potential_payout, 
            request.game_id, description, request.notes)
        
        bet_id = row["id"]
        
        # Insert legs for parlays
        legs_data = []
        if request.bet_type == "parlay" and request.legs:
            for leg in request.legs:
                await conn.execute("""
                    INSERT INTO bet_legs (bet_id, game_id, description, odds)
                    VALUES ($1, $2, $3, $4)
                """, bet_id, leg.game_id, leg.description, leg.odds)
                legs_data.append({"description": leg.description, "odds": leg.odds, "outcome": "pending"})
        
        return BetResponse(
            id=bet_id,
            created_at=row["created_at"].isoformat(),
            sport=row["sport"],
            bet_type=row["bet_type"],
            sportsbook=row["sportsbook"],
            stake=float(row["stake"]),
            odds=row["odds"],
            potential_payout=float(row["potential_payout"]) if row["potential_payout"] else None,
            outcome=row["outcome"],
            cashout_amount=None,
            profit=None,
            game_id=row["game_id"],
            description=row["description"],
            notes=row["notes"],
            legs=legs_data if legs_data else None
        )
    finally:
        await conn.close()


@router.get("")
async def list_bets(
    sport: Optional[str] = Query(None, description="Filter by sport"),
    outcome: Optional[str] = Query(None, description="Filter by outcome"),
    limit: int = Query(50, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """List bets with optional filters."""
    import asyncpg
    
    await ensure_tables()
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Build query
        conditions = []
        params = []
        param_idx = 1
        
        if sport:
            conditions.append(f"sport = ${param_idx}")
            params.append(sport)
            param_idx += 1
        
        if outcome:
            conditions.append(f"outcome = ${param_idx}")
            params.append(outcome)
            param_idx += 1
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = f"""
            SELECT * FROM bets 
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.extend([limit, offset])
        
        rows = await conn.fetch(query, *params)
        
        bets = []
        for row in rows:
            # Get legs if parlay
            legs_data = None
            if row["bet_type"] == "parlay":
                legs_rows = await conn.fetch(
                    "SELECT * FROM bet_legs WHERE bet_id = $1", row["id"]
                )
                legs_data = [
                    {"description": l["description"], "odds": l["odds"], "outcome": l["outcome"]}
                    for l in legs_rows
                ]
            
            bets.append({
                "id": row["id"],
                "created_at": row["created_at"].isoformat(),
                "sport": row["sport"],
                "bet_type": row["bet_type"],
                "sportsbook": row["sportsbook"],
                "stake": float(row["stake"]),
                "odds": row["odds"],
                "potential_payout": float(row["potential_payout"]) if row["potential_payout"] else None,
                "outcome": row["outcome"],
                "cashout_amount": float(row["cashout_amount"]) if row["cashout_amount"] else None,
                "profit": float(row["profit"]) if row["profit"] else None,
                "game_id": row["game_id"],
                "description": row["description"],
                "notes": row["notes"],
                "legs": legs_data
            })
        
        return {"bets": bets, "count": len(bets)}
    finally:
        await conn.close()


@router.get("/{bet_id}")
async def get_bet(bet_id: int):
    """Get a single bet by ID."""
    import asyncpg
    
    await ensure_tables()
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow("SELECT * FROM bets WHERE id = $1", bet_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bet not found")
        
        legs_data = None
        if row["bet_type"] == "parlay":
            legs_rows = await conn.fetch(
                "SELECT * FROM bet_legs WHERE bet_id = $1", bet_id
            )
            legs_data = [
                {"description": l["description"], "odds": l["odds"], "outcome": l["outcome"]}
                for l in legs_rows
            ]
        
        return {
            "id": row["id"],
            "created_at": row["created_at"].isoformat(),
            "sport": row["sport"],
            "bet_type": row["bet_type"],
            "sportsbook": row["sportsbook"],
            "stake": float(row["stake"]),
            "odds": row["odds"],
            "potential_payout": float(row["potential_payout"]) if row["potential_payout"] else None,
            "outcome": row["outcome"],
            "cashout_amount": float(row["cashout_amount"]) if row["cashout_amount"] else None,
            "profit": float(row["profit"]) if row["profit"] else None,
            "game_id": row["game_id"],
            "description": row["description"],
            "notes": row["notes"],
            "legs": legs_data
        }
    finally:
        await conn.close()


@router.patch("/{bet_id}/outcome")
async def update_bet_outcome(bet_id: int, request: UpdateOutcomeRequest):
    """Update bet outcome (win/loss/cashout/pending)."""
    import asyncpg
    
    if request.outcome not in ["win", "loss", "cashout", "pending"]:
        raise HTTPException(status_code=400, detail="Invalid outcome. Use: win, loss, cashout, pending")
    
    if request.outcome == "cashout" and request.cashout_amount is None:
        raise HTTPException(status_code=400, detail="Cash out amount required for cashout outcome")
    
    await ensure_tables()
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Get existing bet
        row = await conn.fetchrow("SELECT * FROM bets WHERE id = $1", bet_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bet not found")
        
        stake = float(row["stake"])
        odds = row["odds"] or 0
        
        # Calculate profit
        profit = calculate_profit(stake, odds, request.outcome, request.cashout_amount)
        
        # Update bet
        await conn.execute("""
            UPDATE bets 
            SET outcome = $1, cashout_amount = $2, profit = $3
            WHERE id = $4
        """, request.outcome, request.cashout_amount, profit, bet_id)
        
        return {
            "id": bet_id,
            "outcome": request.outcome,
            "profit": profit,
            "cashout_amount": request.cashout_amount
        }
    finally:
        await conn.close()


class UpdateBetRequest(BaseModel):
    """Request to update bet details."""
    stake: Optional[float] = None
    odds: Optional[int] = None
    description: Optional[str] = None
    sportsbook: Optional[str] = None
    notes: Optional[str] = None


@router.put("/{bet_id}")
async def update_bet(bet_id: int, request: UpdateBetRequest):
    """Update bet details (stake, odds, description, etc.)."""
    import asyncpg
    
    await ensure_tables()
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Check bet exists
        row = await conn.fetchrow("SELECT * FROM bets WHERE id = $1", bet_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bet not found")
        
        # Build update query dynamically
        updates = []
        params = []
        param_idx = 1
        
        if request.stake is not None:
            updates.append(f"stake = ${param_idx}")
            params.append(request.stake)
            param_idx += 1
        
        if request.odds is not None:
            updates.append(f"odds = ${param_idx}")
            params.append(request.odds)
            param_idx += 1
            
        if request.description is not None:
            updates.append(f"description = ${param_idx}")
            params.append(request.description)
            param_idx += 1
            
        if request.sportsbook is not None:
            updates.append(f"sportsbook = ${param_idx}")
            params.append(request.sportsbook)
            param_idx += 1
            
        if request.notes is not None:
            updates.append(f"notes = ${param_idx}")
            params.append(request.notes)
            param_idx += 1
        
        if not updates:
            return {"id": bet_id, "message": "No changes provided"}
        
        # Recalculate potential payout if stake or odds changed
        new_stake = request.stake if request.stake is not None else float(row["stake"])
        new_odds = request.odds if request.odds is not None else (int(row["odds"]) if row["odds"] else 0)
        
        if new_odds != 0:
            potential_payout = calculate_potential_payout(new_stake, new_odds)
            updates.append(f"potential_payout = ${param_idx}")
            params.append(potential_payout)
            param_idx += 1
        
        params.append(bet_id)
        query = f"UPDATE bets SET {', '.join(updates)} WHERE id = ${param_idx}"
        
        await conn.execute(query, *params)
        
        return {
            "id": bet_id,
            "message": "Bet updated",
            "updated_fields": [u.split(" = ")[0] for u in updates]
        }
    finally:
        await conn.close()


@router.delete("/{bet_id}")
async def delete_bet(bet_id: int):
    """Delete a bet."""
    import asyncpg
    
    await ensure_tables()
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        result = await conn.execute("DELETE FROM bets WHERE id = $1", bet_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Bet not found")
        return {"status": "deleted", "id": bet_id}
    finally:
        await conn.close()


@router.get("/stats/summary")
async def get_bet_stats(
    sport: Optional[str] = Query(None, description="Filter by sport"),
    days: int = Query(30, description="Stats for last N days")
):
    """Get betting statistics summary."""
    import asyncpg
    
    await ensure_tables()
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        conditions = ["created_at > NOW() - INTERVAL '%s days'" % days]
        params = []
        
        if sport:
            conditions.append("sport = $1")
            params.append(sport)
        
        where_clause = "WHERE " + " AND ".join(conditions)
        
        query = f"""
            SELECT 
                COUNT(*) as total_bets,
                COUNT(*) FILTER (WHERE outcome = 'win') as wins,
                COUNT(*) FILTER (WHERE outcome = 'loss') as losses,
                COUNT(*) FILTER (WHERE outcome = 'cashout') as cashouts,
                COUNT(*) FILTER (WHERE outcome = 'pending') as pending,
                COALESCE(SUM(stake), 0) as total_staked,
                COALESCE(SUM(profit), 0) as net_profit,
                COALESCE(SUM(profit) FILTER (WHERE outcome = 'win'), 0) as win_profit,
                COALESCE(SUM(stake) FILTER (WHERE outcome = 'loss'), 0) as loss_amount
            FROM bets
            {where_clause}
        """
        
        row = await conn.fetchrow(query, *params) if params else await conn.fetchrow(query)
        
        total = row["wins"] + row["losses"]
        win_pct = (row["wins"] / total * 100) if total > 0 else 0
        
        return {
            "period_days": days,
            "sport": sport or "all",
            "total_bets": row["total_bets"],
            "wins": row["wins"],
            "losses": row["losses"],
            "cashouts": row["cashouts"],
            "pending": row["pending"],
            "win_percentage": round(win_pct, 1),
            "total_staked": float(row["total_staked"]),
            "net_profit": float(row["net_profit"]),
            "roi": round(float(row["net_profit"]) / float(row["total_staked"]) * 100, 1) if row["total_staked"] else 0
        }
    finally:
        await conn.close()


@router.get("/stats/chart-data")
async def get_chart_data(
    sport: Optional[str] = Query(None, description="Filter by sport"),
    days: int = Query(30, description="Data for last N days")
):
    """
    Get time-series data for betting analytics charts.
    Returns: daily profits, cumulative ROI trend, outcome distribution.
    """
    import asyncpg
    from datetime import datetime, timedelta
    
    await ensure_tables()
    
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        sport_filter = "AND sport = $2" if sport else ""
        params = [days] if not sport else [days, sport]
        
        # Daily profit/loss
        daily_query = f"""
            SELECT 
                DATE(created_at) as bet_date,
                COALESCE(SUM(profit), 0) as daily_profit,
                COALESCE(SUM(stake), 0) as daily_stake,
                COUNT(*) as bet_count,
                SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN outcome = 'cashout' THEN 1 ELSE 0 END) as cashouts
            FROM bets
            WHERE created_at > NOW() - INTERVAL '{days} days'
                AND outcome != 'pending'
                {sport_filter}
            GROUP BY DATE(created_at)
            ORDER BY bet_date ASC
        """
        
        daily_rows = await conn.fetch(daily_query, *params) if sport else await conn.fetch(daily_query)
        
        # Build daily data with cumulative ROI
        daily_data = []
        cumulative_profit = 0
        cumulative_stake = 0
        
        for row in daily_rows:
            cumulative_profit += float(row["daily_profit"])
            cumulative_stake += float(row["daily_stake"])
            cumulative_roi = (cumulative_profit / cumulative_stake * 100) if cumulative_stake > 0 else 0
            
            daily_data.append({
                "date": row["bet_date"].isoformat(),
                "profit": float(row["daily_profit"]),
                "stake": float(row["daily_stake"]),
                "bets": row["bet_count"],
                "wins": row["wins"],
                "losses": row["losses"],
                "cashouts": row["cashouts"],
                "cumulative_profit": cumulative_profit,
                "cumulative_roi": round(cumulative_roi, 2)
            })
        
        # Outcome totals for pie chart
        totals_query = f"""
            SELECT 
                outcome,
                COUNT(*) as count,
                COALESCE(SUM(profit), 0) as profit
            FROM bets
            WHERE created_at > NOW() - INTERVAL '{days} days'
                AND outcome != 'pending'
                {sport_filter}
            GROUP BY outcome
        """
        
        totals_rows = await conn.fetch(totals_query, *params) if sport else await conn.fetch(totals_query)
        
        outcome_distribution = {
            "wins": 0,
            "losses": 0,
            "cashouts": 0,
            "win_profit": 0,
            "loss_amount": 0,
            "cashout_profit": 0
        }
        
        for row in totals_rows:
            if row["outcome"] == "win":
                outcome_distribution["wins"] = row["count"]
                outcome_distribution["win_profit"] = float(row["profit"])
            elif row["outcome"] == "loss":
                outcome_distribution["losses"] = row["count"]
                outcome_distribution["loss_amount"] = abs(float(row["profit"]))
            elif row["outcome"] == "cashout":
                outcome_distribution["cashouts"] = row["count"]
                outcome_distribution["cashout_profit"] = float(row["profit"])
        
        return {
            "period_days": days,
            "sport": sport or "all",
            "daily_data": daily_data,
            "outcome_distribution": outcome_distribution,
            "summary": {
                "total_profit": cumulative_profit,
                "total_stake": cumulative_stake,
                "roi": round((cumulative_profit / cumulative_stake * 100), 2) if cumulative_stake > 0 else 0,
                "total_bets": sum(d["bets"] for d in daily_data)
            }
        }
    finally:
        await conn.close()
