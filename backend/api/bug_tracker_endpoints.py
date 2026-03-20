from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/bugs", tags=["Bug Tracker"])
from api.db_endpoints import get_db_connection

from src.config import DATABASE_URL

# ==================== Models ====================

class BugCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    severity: str = "Medium"
    type: str = "Bug"
    status: str = "New"

class BugUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    type: Optional[str] = None

class BugStatusUpdate(BaseModel):
    status: str

# ==================== SQL ====================

CREATE_BUGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bugs (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    title VARCHAR(200) NOT NULL,
    description TEXT,
    severity VARCHAR(20) DEFAULT 'Medium',
    type VARCHAR(20) DEFAULT 'Bug',
    status VARCHAR(20) DEFAULT 'New'
);

CREATE INDEX IF NOT EXISTS idx_bugs_status ON bugs(status);
CREATE INDEX IF NOT EXISTS idx_bugs_severity ON bugs(severity);
"""

_initialized = False

async def ensure_table():
    global _initialized
    if _initialized: return
    try:
        import asyncpg
        conn = await get_db_connection(request)
        try:
            await conn.execute(CREATE_BUGS_TABLE_SQL)
            _initialized = True
            logger.info("Bug tracker table initialized")
        finally:
            if hasattr(request.app.state, 'pool') and request.app.state.pool:
                await request.app.state.pool.release(conn)
            else:
                await conn.close()
    except Exception as e:
        logger.error(f"Failed to init bug table: {e}")

# ==================== Endpoints ====================

@router.get("")
async def list_bugs(request: Request):
    import asyncpg
    await ensure_table()

    conn = await get_db_connection(request)
    try:
        rows = await conn.fetch("SELECT * FROM bugs ORDER BY created_at DESC")
        bugs = []
        for r in rows:
            bugs.append({
                "id": r["id"],
                "created_at": r["created_at"].isoformat(),
                "title": r["title"],
                "description": r["description"],
                "severity": r["severity"],
                "type": r["type"],
                "status": r["status"]
            })
        return {"bugs": bugs}
    finally:
        if hasattr(request.app.state, 'pool') and request.app.state.pool:
            await request.app.state.pool.release(conn)
        else:
            await conn.close()

@router.post("")
async def create_bug(request: Request, bug: BugCreate):
    import asyncpg
    await ensure_table()

    conn = await get_db_connection(request)
    try:
        row = await conn.fetchrow("""
            INSERT INTO bugs (title, description, severity, type, status)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
        """, bug.title, bug.description, bug.severity, bug.type, bug.status)
        return {"status": "created", "id": row["id"]}
    finally:
        if hasattr(request.app.state, 'pool') and request.app.state.pool:
            await request.app.state.pool.release(conn)
        else:
            await conn.close()

@router.put("/{bug_id}")
async def update_bug(request: Request, bug_id: int, bug: BugUpdate):
    import asyncpg
    await ensure_table()

    conn = await get_db_connection(request)
    try:
        # Dynamic update
        fields = []
        params = []
        if bug.title: fields.append(f"title = ${len(params)+1}"); params.append(bug.title)
        if bug.description: fields.append(f"description = ${len(params)+1}"); params.append(bug.description)
        if bug.severity: fields.append(f"severity = ${len(params)+1}"); params.append(bug.severity)
        if bug.status: fields.append(f"status = ${len(params)+1}"); params.append(bug.status)
        if bug.type: fields.append(f"type = ${len(params)+1}"); params.append(bug.type)
        
        if not fields: return {"message": "no changes"}
        
        params.append(bug_id)
        query = f"UPDATE bugs SET {', '.join(fields)} WHERE id = ${len(params)}"
        await conn.execute(query, *params)
        return {"status": "updated"}
    finally:
        if hasattr(request.app.state, 'pool') and request.app.state.pool:
            await request.app.state.pool.release(conn)
        else:
            await conn.close()

@router.patch("/{bug_id}/status")
async def update_bug_status(request: Request, bug_id: int, req: BugStatusUpdate):
    import asyncpg
    await ensure_table()

    conn = await get_db_connection(request)
    try:
        await conn.execute("UPDATE bugs SET status = $1 WHERE id = $2", req.status, bug_id)
        return {"status": "updated", "id": bug_id}
    finally:
        if hasattr(request.app.state, 'pool') and request.app.state.pool:
            await request.app.state.pool.release(conn)
        else:
            await conn.close()

@router.delete("/{bug_id}")
async def delete_bug(request: Request, bug_id: int):
    import asyncpg
    await ensure_table()

    conn = await get_db_connection(request)
    try:
        await conn.execute("DELETE FROM bugs WHERE id = $1", bug_id)
        return {"status": "deleted"}
    finally:
        if hasattr(request.app.state, 'pool') and request.app.state.pool:
            await request.app.state.pool.release(conn)
        else:
            await conn.close()
