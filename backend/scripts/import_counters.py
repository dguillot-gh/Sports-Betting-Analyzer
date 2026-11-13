"""Pure helpers for distinguishing NEW rows from UPDATED rows on upserts.

Background: ``batch_upsert`` (asyncpg executemany) can only report the total
number of rows processed. Importers that needed it split the work by loading
the set of pre-existing content hashes first (``SELECT content_hash``) and
comparing — so the nightly import log's ``new_rows_imported`` was either
inaccurate (counted by hash equality, but duplicate rows in the file were
double-counted) or hardcoded to 0 (NHL, NFL season stats).

These helpers make that split exact and testable without a database.
"""
from typing import Any, Dict, List, Sequence, Set, Tuple

ContentHash = Any  # str in practice


def partition_by_hash(
    records: Sequence[Tuple[Any, ...]],
    hash_index: int,
    existing_hashes: Set[ContentHash],
) -> Tuple[List[Tuple[Any, ...]], List[Tuple[Any, ...]]]:
    """Split records into (new, updated) by whether their content hash exists.

    ``hash_index`` is the position of the content-hash column in each record
    tuple. The input order is preserved in both outputs.
    """
    new: List[Tuple[Any, ...]] = []
    updated: List[Tuple[Any, ...]] = []
    for record in records:
        target = updated if record[hash_index] in existing_hashes else new
        target.append(record)
    return new, updated


async def split_by_existing_hashes(
    conn,
    table: str,
    records: Sequence[Tuple[Any, ...]],
    hash_index: int,
    sport_id: Any = None,
) -> Tuple[List[Tuple[Any, ...]], List[Tuple[Any, ...]]]:
    """Same as ``partition_by_hash`` but loads existing hashes from Postgres.

    Only hashes actually present in ``records`` are queried, so the lookup is
    bounded by the import size, not the table size:
        SELECT content_hash FROM {table} [WHERE sport_id = $1]
        AND content_hash = ANY($2)
    ``table`` must be a hardcoded constant from the importer (not user input).
    """
    hashes = list(dict.fromkeys(record[hash_index] for record in records))
    if not hashes:
        return [], []

    if sport_id is not None:
        rows = await conn.fetch(
            f"SELECT content_hash FROM {table} WHERE sport_id = $1 AND content_hash = ANY($2)",
            sport_id, hashes,
        )
    else:
        rows = await conn.fetch(
            f"SELECT content_hash FROM {table} WHERE content_hash = ANY($2)",
            hashes,
        )
    existing = {row["content_hash"] for row in rows}
    return partition_by_hash(records, hash_index, existing)


def summarize(new: Sequence, updated: Sequence, total: int = None) -> Dict[str, int]:
    """Standard import summary shape used by importer return values."""
    total = len(new) + len(updated) if total is None else total
    return {"total": total, "new": len(new), "updated": len(updated)}
