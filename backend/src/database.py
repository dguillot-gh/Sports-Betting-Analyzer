"""
Database Connection Pool
========================
Centralized asyncpg connection pool for all database operations.
Improves performance by reusing connections instead of creating new ones per request.
"""

import asyncpg
import logging
from typing import Optional
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from src.config import DATABASE_URL

# Global pool instance
_pool: Optional[asyncpg.Pool] = None


async def init_pool(min_size: int = 5, max_size: int = 20) -> asyncpg.Pool:
    """Initialize the connection pool. Call once at app startup."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=min_size,
            max_size=max_size,
            command_timeout=60,
            statement_cache_size=100,
        )
        logger.info(f"Database pool initialized (min={min_size}, max={max_size})")
    return _pool


async def close_pool():
    """Close the connection pool. Call at app shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


async def get_pool() -> asyncpg.Pool:
    """Get the connection pool, initializing if needed."""
    global _pool
    if _pool is None:
        await init_pool()
    return _pool


@asynccontextmanager
async def get_connection():
    """
    Context manager for getting a connection from the pool.
    
    Usage:
        async with get_connection() as conn:
            result = await conn.fetch("SELECT * FROM bets")
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def execute(query: str, *args):
    """Execute a query and return the result string."""
    async with get_connection() as conn:
        return await conn.execute(query, *args)


async def fetch(query: str, *args):
    """Fetch multiple rows."""
    async with get_connection() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args):
    """Fetch a single row."""
    async with get_connection() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args):
    """Fetch a single value."""
    async with get_connection() as conn:
        return await conn.fetchval(query, *args)
