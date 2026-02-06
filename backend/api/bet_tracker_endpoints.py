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
from typing import Optional, List, Union
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Query, File, UploadFile
import io
import csv

import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bets", tags=["Bet Tracker"])

# Use environment variable with fallback for local development
from src.config import DATABASE_URL

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
    game_name: Optional[str] = Field(None, description="Game name (e.g. Chiefs vs Bills)")
    description: Optional[str] = Field(None, description="Bet description")
    source: str = Field("manual", description="manual or auto")
    legs: Optional[List[BetLeg]] = Field(None, description="Parlay legs")
    notes: Optional[str] = None
    # AI Fields
    expected_value: Optional[float] = None
    recommendation: Optional[str] = None
    confidence_score: Optional[float] = None
    team1: Optional[str] = None
    team2: Optional[str] = None
    player_name: Optional[str] = None
    game_date: Optional[str] = None
    clv_percent: Optional[float] = None


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
    game_name: Optional[str]
    description: Optional[str]
    source: str = "manual"
    notes: Optional[str]
    legs: Optional[List[dict]] = None
    # AI Fields
    expected_value: Optional[float] = None
    recommendation: Optional[str] = None
    confidence_score: Optional[float] = None
    team1: Optional[str] = None
    team2: Optional[str] = None
    player_name: Optional[str] = None
    game_date: Optional[str] = None
    clv_percent: Optional[float] = None


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
    game_name VARCHAR(200),
    description VARCHAR(200),
    source VARCHAR(20) DEFAULT 'manual',
    notes TEXT,
    -- AI Fields for unification
    expected_value DECIMAL(10,2),
    recommendation VARCHAR(50),
    confidence_score DECIMAL(5,2),
    team1 VARCHAR(200),
    team2 VARCHAR(200),
    player_name VARCHAR(200),
    game_date TIMESTAMPTZ,
    clv_percent DECIMAL(5,2)
);

CREATE TABLE IF NOT EXISTS bet_legs (
    id SERIAL PRIMARY KEY,
    bet_id INT REFERENCES bets(id) ON DELETE CASCADE,
    game_id VARCHAR(100),
    description VARCHAR(200),
    odds INT,
    outcome VARCHAR(10) DEFAULT 'pending'
);

);
"""

_tables_initialized = False


# ==================== Helper Functions ====================

def to_float(value: Union[float, Decimal, int, None]) -> float:
    """Safely convert Decimal or other numeric types to float."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def calculate_potential_payout(stake: Union[float, Decimal], odds: int) -> float:
    """Calculate potential payout from American odds."""
    stake = to_float(stake)
    if odds > 0:
        return float(stake) + (float(stake) * float(odds) / 100.0)
    else:
        return float(stake) + (float(stake) * 100.0 / float(abs(odds)))


def calculate_profit(stake: Union[float, Decimal], odds: int, outcome: str, cashout_amount: Optional[Union[float, Decimal]] = None) -> float:
    """Calculate profit based on outcome."""
    stake = to_float(stake)
    cashout_amount = to_float(cashout_amount) if cashout_amount is not None else None
    
    if outcome == "win":
        if odds > 0:
            return float(stake) * float(odds) / 100.0
        else:
            return float(stake) * 100.0 / float(abs(odds))
    elif outcome == "loss":
        return -stake
    elif outcome == "cashout" and cashout_amount is not None:
        return cashout_amount - stake
    return 0.0


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
        
        # Check and add new columns if they don't exist (migrations)
        try:
            # Check for sport (core column that might be missing in very old schemas)
            val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='sport'")
            if not val:
                logger.info("Adding sport column to bets table")
                await conn.execute("ALTER TABLE bets ADD COLUMN sport VARCHAR(20)")

            # Check for bet_type
            val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='bet_type'")
            if not val:
                logger.info("Adding bet_type column to bets table")
                await conn.execute("ALTER TABLE bets ADD COLUMN bet_type VARCHAR(20) DEFAULT 'single'")

            # Check for game_name
            val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='game_name'")
            if not val:
                logger.info("Adding game_name column to bets table")
                await conn.execute("ALTER TABLE bets ADD COLUMN game_name VARCHAR(200)")
                
            # Check for source
            val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='source'")
            if not val:
                logger.info("Adding source column to bets table")
                await conn.execute("ALTER TABLE bets ADD COLUMN source VARCHAR(20) DEFAULT 'manual'")

            # Check for AI Unification columns
            val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='expected_value'")
            if not val:
                logger.info("Adding AI unification columns to bets table")
                await conn.execute("ALTER TABLE bets ADD COLUMN expected_value DECIMAL(10,2)")
                await conn.execute("ALTER TABLE bets ADD COLUMN recommendation VARCHAR(50)")
                await conn.execute("ALTER TABLE bets ADD COLUMN confidence_score DECIMAL(5,2)")
                await conn.execute("ALTER TABLE bets ADD COLUMN team1 VARCHAR(200)")
                await conn.execute("ALTER TABLE bets ADD COLUMN team2 VARCHAR(200)")
                await conn.execute("ALTER TABLE bets ADD COLUMN player_name VARCHAR(200)")
                await conn.execute("ALTER TABLE bets ADD COLUMN game_date TIMESTAMPTZ")
            
            # Check for clv_percent
            val = await conn.fetchval("SELECT column_name FROM information_schema.columns WHERE table_name='bets' AND column_name='clv_percent'")
            if not val:
                logger.info("Adding clv_percent column to bets table")
                await conn.execute("ALTER TABLE bets ADD COLUMN clv_percent DECIMAL(5,2)")

            # Finalize indexes after column migrations
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_sport ON bets(sport)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_outcome ON bets(outcome)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_created ON bets(created_at)")
        except Exception as e:
            logger.error(f"Schema migration error: {e}")
            
        await conn.close()
        _tables_initialized = True
        logger.info("Bet tracker tables initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize bet tables (database connection: {DATABASE_URL[:30]}...): {e}")
        # Re-raise to ensure the endpoint returns a 500 with context
        raise HTTPException(
            status_code=500, 
            detail=f"Bet analysis database connection failed. Ensure PostgreSQL is running. Error: {str(e)}"
        )


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
            INSERT INTO bets (sport, bet_type, sportsbook, stake, odds, potential_payout, game_id, game_name, description, source, notes,
                             expected_value, recommendation, confidence_score, team1, team2, player_name, game_date, clv_percent)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            RETURNING *
        """, request.sport, request.bet_type, request.sportsbook, 
            request.stake, combined_odds, potential_payout, 
            request.game_id, request.game_name, description, request.source, request.notes,
            request.expected_value, request.recommendation, request.confidence_score,
            request.team1, request.team2, request.player_name, 
            datetime.fromisoformat(request.game_date.replace("Z", "+00:00")) if request.game_date else None,
            request.clv_percent)
        
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
            stake=to_float(row["stake"]),
            odds=row["odds"],
            potential_payout=to_float(row["potential_payout"]) if row["potential_payout"] else None,
            outcome=row["outcome"] or "pending",
            cashout_amount=None,
            profit=None,
            game_id=row["game_id"],
            game_name=row["game_name"],
            description=row["description"],
            source=row["source"] or "manual",
            notes=row["notes"],
            legs=legs_data if legs_data else None,
            expected_value=to_float(row["expected_value"]) if row["expected_value"] is not None else None,
            recommendation=row["recommendation"],
            confidence_score=to_float(row["confidence_score"]) if row["confidence_score"] is not None else None,
            team1=row["team1"],
            team2=row["team2"],
            player_name=row["player_name"],
            game_date=row["game_date"].isoformat() if row["game_date"] else None,
            clv_percent=to_float(row["clv_percent"]) if row["clv_percent"] is not None else None
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
    import traceback
    
    try:
        await ensure_tables()
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Database connection error in list_bets: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")
        
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
                "stake": to_float(row["stake"]),
                "odds": row["odds"],
                "potential_payout": to_float(row["potential_payout"]) if row["potential_payout"] else None,
                "outcome": row["outcome"],
                "cashout_amount": to_float(row["cashout_amount"]) if row["cashout_amount"] else None,
                "profit": to_float(row["profit"]) if row["profit"] else None,
                "game_id": row["game_id"],
                "game_name": row.get("game_name"),
                "description": row["description"],
                "source": row.get("source", "manual"),
                "notes": row["notes"],
                "legs": legs_data,
                "expected_value": to_float(row["expected_value"]) if row["expected_value"] is not None else None,
                "recommendation": row["recommendation"],
                "confidence_score": to_float(row["confidence_score"]) if row["confidence_score"] is not None else None,
                "team1": row["team1"],
                "team2": row["team2"],
                "player_name": row["player_name"],
                "game_date": row["game_date"].isoformat() if row["game_date"] else None,
                "clv_percent": to_float(row["clv_percent"]) if row["clv_percent"] is not None else None
            })
        
        return {"bets": bets, "count": len(bets)}
    except Exception as e:
        logger.error(f"Query error in list_bets: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
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
            "stake": to_float(row["stake"]),
            "odds": row["odds"],
            "potential_payout": to_float(row["potential_payout"]) if row["potential_payout"] else None,
            "outcome": row["outcome"],
            "cashout_amount": to_float(row["cashout_amount"]) if row["cashout_amount"] else None,
            "profit": to_float(row["profit"]) if row["profit"] else None,
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
        
        stake = row["stake"]  # Keep as Decimal for DB operations
        odds = row["odds"] or 0
        
        # Calculate profit (converts to float internally)
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
        new_stake = request.stake if request.stake is not None else to_float(row["stake"])
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


@router.delete("/all")
async def clear_all_bets():
    """Wipe all bet data."""
    import asyncpg
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("TRUNCATE TABLE bet_legs RESTART IDENTITY CASCADE;")
        await conn.execute("TRUNCATE TABLE bets RESTART IDENTITY CASCADE;")
        return {"status": "success", "message": "All bet history cleared"}
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
    import traceback
    
    try:
        await ensure_tables()
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Database connection error in /stats/summary: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")
        
    try:
        if days > 0:
            conditions = ["created_at > NOW() - INTERVAL '%s days'" % days]
        else:
            conditions = []
        
        params = []
        
        if sport:
            conditions.append("sport = $1")
            params.append(sport)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
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
        
        total_staked = to_float(row["total_staked"])
        net_profit = to_float(row["net_profit"])
        
        return {
            "period_days": days,
            "sport": sport or "all",
            "total_bets": row["total_bets"],
            "wins": row["wins"],
            "losses": row["losses"],
            "cashouts": row["cashouts"],
            "pending": row["pending"],
            "win_percentage": round(win_pct, 1),
            "total_staked": total_staked,
            "net_profit": net_profit,
            "roi": round(net_profit / total_staked * 100, 1) if total_staked else 0
        }
    except Exception as e:
        logger.error(f"Query error in /stats/summary: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
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
    import traceback
    
    try:
        await ensure_tables()
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Database connection error in get_chart_data: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")
        
    try:
        if days > 0:
            date_filter = f"WHERE created_at > NOW() - INTERVAL '{days} days'"
        else:
            date_filter = "WHERE 1=1"
        
        sport_filter = "AND sport = $2" if sport else ""
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
            {date_filter}
                AND outcome != 'pending'
                {sport_filter}
            GROUP BY DATE(created_at)
            ORDER BY bet_date ASC
        """
        
        daily_params = []
        if sport: daily_params.append(sport)
        
        daily_rows = await conn.fetch(daily_query, *daily_params) if daily_params else await conn.fetch(daily_query)
        
        # Build daily data with cumulative ROI
        daily_data = []
        cumulative_profit = 0.0
        cumulative_stake = 0.0
        
        for row in daily_rows:
            daily_profit = to_float(row["daily_profit"])
            daily_stake = to_float(row["daily_stake"])
            
            cumulative_profit += daily_profit
            cumulative_stake += daily_stake
            cumulative_roi = (cumulative_profit / cumulative_stake * 100) if cumulative_stake > 0 else 0
            
            daily_data.append({
                "date": row["bet_date"].isoformat(),
                "profit": daily_profit,
                "stake": daily_stake,
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
            {date_filter}
                AND outcome != 'pending'
                {sport_filter}
            GROUP BY outcome
        """
        
        totals_rows = await conn.fetch(totals_query, *daily_params) if sport else await conn.fetch(totals_query)
        
        outcome_distribution = {
            "wins": 0,
            "losses": 0,
            "cashouts": 0,
            "win_profit": 0.0,
            "loss_amount": 0.0,
            "cashout_profit": 0.0
        }
        
        for row in totals_rows:
            profit_val = to_float(row["profit"])
            if row["outcome"] == "win":
                outcome_distribution["wins"] = row["count"]
                outcome_distribution["win_profit"] = profit_val
            elif row["outcome"] == "loss":
                outcome_distribution["losses"] = row["count"]
                outcome_distribution["loss_amount"] = abs(profit_val)
            elif row["outcome"] == "cashout":
                outcome_distribution["cashouts"] = row["count"]
                outcome_distribution["cashout_profit"] = profit_val
        
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
    except Exception as e:
        logger.error(f"Query error in get_chart_data: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
    finally:
        await conn.close()


@router.post("/import-csv")
async def import_bets_csv(file: UploadFile = File(...)):
    """Import bets from Juice Reel CSV (Legacy/Direct)."""
    # ... (keeping existing logic for compatibility but can redirect to the new universal logic later)
    # Actually, let's keep it as is for now and add the new one below.
    # [Rest of existing import-csv code]
    import asyncpg
    from collections import defaultdict
    import io
    import csv
    
    content = await file.read()
    string_content = content.decode('utf-8')
    f = io.StringIO(string_content)
    reader = csv.DictReader(f)
    
    # Group by juice_bet_id
    bets_map = defaultdict(list)
    for row in reader:
        bets_map[row.get('juice_bet_id', 'unknown')].append(row)
    
    await ensure_tables()
    conn = await asyncpg.connect(DATABASE_URL)
    
    imported_count = 0
    errors = []
    
    try:
        async with conn.transaction():
            for bet_id, legs in bets_map.items():
                try:
                    first_leg = legs[0]
                    num_legs = int(first_leg.get('number_of_legs', 1))
                    stake = float(first_leg.get('risk_amount', 0))
                    odds = int(first_leg.get('odds_american', 0))
                    profit = float(first_leg.get('amount_won_or_lost', 0))
                    outcome_raw = first_leg.get('bet_result', 'pending').lower()
                    
                    if outcome_raw == "cashedout": outcome = "cashout"
                    elif outcome_raw in ["won", "loss", "pending"]: outcome = outcome_raw
                    else: outcome = "pending"
                        
                    potential_payout = calculate_potential_payout(stake, odds)
                    
                    if num_legs == 1:
                        sport_raw = first_leg.get('leg_sport', 'unknown').lower()
                        league_raw = first_leg.get('leg_league', 'unknown').lower()
                        if "nba" in league_raw: sport = "nba"
                        elif "nfl" in league_raw: sport = "nfl"
                        elif "mlb" in league_raw: sport = "mlb"
                        elif "basketball" in sport_raw: sport = "nba"
                        elif "football" in sport_raw: sport = "nfl"
                        elif "racing" in sport_raw: sport = "nascar"
                        else: sport = sport_raw[:20]
                        
                        game_name = first_leg.get('event_name', 'Unknown Event')
                        description = first_leg.get('leg_description', '')
                    else:
                        sport = "parlay"
                        game_name = f"{num_legs}-leg parlay"
                        description = ", ".join([l.get('event_name', '') for l in legs])[:200]
                    
                    bet_row = await conn.fetchrow("""
                        INSERT INTO bets (sport, bet_type, sportsbook, stake, odds, potential_payout, 
                                         outcome, profit, game_name, description, source, 
                                         game_date, clv_percent)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                        RETURNING id
                    """, sport, "single" if num_legs == 1 else "parlay", first_leg.get('sportsbook', 'Unknown'),
                        stake, odds, potential_payout, outcome, profit, game_name, description, 
                        "import", datetime.fromisoformat(first_leg.get('date_placed', datetime.now().isoformat()).replace("+00", "+00:00")),
                        float(first_leg['clv_percent']) if first_leg.get('clv_percent') else None)
                    
                    bet_db_id = bet_row['id']
                    for leg in legs:
                        await conn.execute("""
                            INSERT INTO bet_legs (bet_id, description, odds, outcome)
                            VALUES ($1, $2, $3, $4)
                        """, bet_db_id, leg.get('leg_description', ''), int(leg.get('leg_vig', 0)), "pending") 
                    
                    imported_count += 1
                except Exception as e:
                    errors.append(f"Bet {bet_id}: {str(e)}")
        
        return {"status": "success", "imported_count": imported_count, "error_count": len(errors), "errors": errors[:10]}
    finally:
        await conn.close()


# ==================== Universal Importer ====================

class HeaderMapper:
    """Intelligent header mapping for spreadsheets."""
    MAPPINGS = {
        "stake": ["stake", "risk", "amount", "wager", "risk_amount", "bet_amount"],
        "odds": ["odds", "price", "line", "odds_american", "american_odds"],
        "sport": ["sport", "league", "category", "leg_sport", "leg_league"],
        "outcome": ["outcome", "result", "status", "bet_result"],
        "date": ["date", "placed at", "timestamp", "date_placed", "datetime"],
        "description": ["description", "teams/player", "event", "event_name", "bet", "leg_description"],
        "sportsbook": ["sportsbook", "book", "site"],
        "profit": ["profit", "net", "amount_won_or_lost", "win/loss"],
    }

    @classmethod
    def map_headers(cls, df_columns):
        mapped = {}
        cols = [c.lower().strip() for c in df_columns]
        for field, aliases in cls.MAPPINGS.items():
            for alias in aliases:
                if alias in cols:
                    # Find original column name
                    idx = cols.index(alias)
                    mapped[field] = df_columns[idx]
                    break
        return mapped

def sanitize_value(val, type_to):
    """Clean and convert values."""
    if val is None or (isinstance(val, float) and os.path.isfile(str(val))): # Handle NaN
        return None
    
    s_val = str(val).strip().replace("$", "").replace(",", "")
    
    if type_to == "float":
        try: return float(s_val)
        except: return 0.0
    if type_to == "int":
        try: return int(float(s_val))
        except: return 0
    if type_to == "outcome":
        low = s_val.lower()
        if "won" in low or "win" in low or "w" == low: return "win"
        if "loss" in low or "lost" in low or "l" == low: return "loss"
        if "cash" in low or "cashed" in low: return "cashout"
        return "pending"
    return s_val

@router.post("/preview-import")
async def preview_import(file: UploadFile = File(...)):
    """Preview a bet import from CSV or Excel."""
    import pandas as pd
    import io
    
    content = await file.read()
    filename = file.filename.lower()
    
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Use CSV or Excel.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    # Map headers
    mapping = HeaderMapper.map_headers(df.columns)
    required = ["stake", "description"] # Minimal requirements
    missing = [f for f in required if f not in mapping]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(missing)}")

    # Process rows
    preview_bets = []
    # Use grouped logic for parlays (if ID exists) or just treat rows as individuals
    id_col = next((c for c in df.columns if "id" in c.lower()), None)
    
    for _, row in df.iterrows():
        # Sanitize
        bet = {
            "id_in_file": str(row[id_col]) if id_col else None,
            "date": sanitize_value(row.get(mapping.get("date")), "str") or datetime.now().isoformat(),
            "sport": sanitize_value(row.get(mapping.get("sport")), "str") or "other",
            "description": sanitize_value(row.get(mapping.get("description")), "str"),
            "stake": sanitize_value(row.get(mapping.get("stake")), "float"),
            "odds": sanitize_value(row.get(mapping.get("odds")), "int"),
            "outcome": sanitize_value(row.get(mapping.get("outcome")), "outcome"),
            "profit": sanitize_value(row.get(mapping.get("profit")), "float"),
            "sportsbook": sanitize_value(row.get(mapping.get("sportsbook")), "str") or "Unknown"
        }
        preview_bets.append(bet)

    # Simplified parlay detection: group by ID if provided
    if id_col:
        from collections import defaultdict
        grouped = defaultdict(list)
        for b in preview_bets:
            grouped[b["id_in_file"]].append(b)
        
        final_preview = []
        for bid, legs in grouped.items():
            if len(legs) > 1:
                master = legs[0].copy()
                master["bet_type"] = "parlay"
                master["description"] = f"{len(legs)}-leg parlay: {legs[0]['description']}..."
                master["legs"] = legs
                final_preview.append(master)
            else:
                l = legs[0]
                l["bet_type"] = "single"
                final_preview.append(l)
        preview_bets = final_preview
    else:
        for b in preview_bets: b["bet_type"] = "single"

    return {"bets": preview_bets, "total_count": len(preview_bets)}

@router.post("/confirm-import")
async def confirm_import(bets: List[dict]):
    """Save finalized bets to database."""
    import asyncpg
    from datetime import datetime
    
    await ensure_tables()
    conn = await asyncpg.connect(DATABASE_URL)
    
    imported_count = 0
    try:
        async with conn.transaction():
            for bet in bets:
                # Calculate potential payout if missing
                potential = calculate_potential_payout(bet["stake"], bet["odds"])
                
                # Insert master
                try:
                    game_date = datetime.fromisoformat(bet["date"].replace("Z", "+00:00"))
                except:
                    game_date = datetime.now()

                bet_row = await conn.fetchrow("""
                    INSERT INTO bets (sport, bet_type, sportsbook, stake, odds, potential_payout, 
                                     outcome, profit, description, game_name, source, game_date)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    RETURNING id
                """, bet.get("sport", "other")[:20], bet.get("bet_type", "single"), bet.get("sportsbook", "Unknown")[:50],
                    bet.get("stake", 0.0), bet.get("odds", 0), potential, bet.get("outcome", "pending"), 
                    bet.get("profit", 0.0), bet.get("description", "")[:200], bet.get("description", "")[:100], 
                    "universal_import", game_date)
                
                # Insert legs if parlay
                if bet.get("legs"):
                    for leg in bet["legs"]:
                        await conn.execute("""
                            INSERT INTO bet_legs (bet_id, description, odds, outcome)
                            VALUES ($1, $2, $3, $4)
                        """, bet_row["id"], leg.get("description", "")[:200], leg.get("odds", 0), leg.get("outcome", "pending"))
                
                imported_count += 1
        return {"status": "success", "imported": imported_count}
    finally:
        await conn.close()
