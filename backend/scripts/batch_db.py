"""
Batch database operations for import scripts.
Uses asyncpg executemany() with pipelining for 5-10x faster inserts.
"""
import logging
import gc
from typing import List, Tuple, Any, Optional, Callable

logger = logging.getLogger(__name__)

# Default batch size - balances speed vs memory on 2GB servers
BATCH_SIZE = 500


async def batch_upsert(
    conn,
    sql: str,
    records: List[Tuple],
    batch_size: int = BATCH_SIZE,
    progress_callback: Optional[Callable] = None,
    label: str = "records"
) -> int:
    """
    Execute an upsert SQL statement in batches using executemany().
    
    asyncpg's executemany() uses internal pipelining, sending multiple
    queries without waiting for each response. This dramatically reduces
    network round-trips vs individual execute() calls.
    
    Args:
        conn: asyncpg connection
        sql: SQL with $1, $2... placeholders (ON CONFLICT supported)
        records: List of tuples, each matching the SQL placeholders
        batch_size: Number of records per executemany() call
        progress_callback: Optional progress reporting function
        label: Human-readable label for progress messages
        
    Returns:
        Number of records successfully processed
    """
    total = len(records)
    processed = 0
    
    for start in range(0, total, batch_size):
        batch = records[start:start + batch_size]
        
        try:
            await conn.executemany(sql, batch)
            processed += len(batch)
        except Exception as e:
            # Fallback: retry row-by-row so one bad row doesn't kill the batch
            logger.warning(f"Batch insert failed ({label}), retrying row-by-row: {e}")
            for record in batch:
                try:
                    await conn.execute(sql, *record)
                    processed += 1
                except Exception as row_err:
                    logger.debug(f"Skipping bad row in {label}: {row_err}")
        
        if progress_callback and (start + batch_size) % (batch_size * 5) == 0:
            progress_callback(f"Importing {label} {processed}/{total}...")
        
        # Periodic memory cleanup
        if start % (batch_size * 10) == 0:
            gc.collect()
    
    return processed


async def batch_upsert_returning(
    conn,
    sql: str,
    records: List[Tuple],
    batch_size: int = BATCH_SIZE,
    label: str = "records"
) -> List[Any]:
    """
    Execute upsert with RETURNING clause, collecting returned values.
    Uses row-by-row execution since executemany doesn't support RETURNING,
    but processes in logical batches for gc.collect().
    
    Use this only when you NEED the returned values (e.g., entity IDs).
    For simple inserts, use batch_upsert() instead.
    """
    results = []
    
    for i, record in enumerate(records):
        try:
            val = await conn.fetchval(sql, *record)
            if val is not None:
                results.append(val)
        except Exception as e:
            logger.debug(f"Error in {label} row {i}: {e}")
        
        if i % (batch_size * 2) == 0 and i > 0:
            gc.collect()
    
    return results
