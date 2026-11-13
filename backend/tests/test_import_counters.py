"""Tests for the new-vs-updated import counters (backend/scripts/import_counters.py).

Regression context: NHL/NFL nightly imports reported new_rows_imported = 0
even when new games were being saved (NHL totals climbed 47,930 -> 48,080
across two nights). Partitions by pre-existing content hash must be exact.
"""
from scripts.import_counters import partition_by_hash, summarize


def _records():
    # tuple shape: (sport_id, season, series, metadata, content_hash)
    return [
        (1, 2026, "nhl", "g1", "h-existing-1"),
        (1, 2026, "nhl", "g2", "h-existing-2"),
        (1, 2026, "nhl", "g3-new", "h-new-1"),
        (1, 2026, "nhl", "g4-new", "h-new-2"),
    ]


def test_Partition_Splits_By_Existing_Hashes():
    records = _records()
    existing = {"h-existing-1", "h-existing-2"}
    new, updated = partition_by_hash(records, hash_index=4, existing_hashes=existing)
    assert [r[4] for r in new] == ["h-new-1", "h-new-2"]
    assert [r[4] for r in updated] == ["h-existing-1", "h-existing-2"]


def test_Partition_Preserves_Input_Order():
    records = _records()
    existing = set()
    new, updated = partition_by_hash(records, hash_index=4, existing_hashes=existing)
    assert new == records
    assert updated == []


def test_Partition_All_Existing():
    records = _records()
    existing = {r[4] for r in records}
    new, updated = partition_by_hash(records, hash_index=4, existing_hashes=existing)
    assert new == []
    assert updated == records


def test_Partition_Empty_Records():
    assert partition_by_hash([], hash_index=4, existing_hashes={"x"}) == ([], [])


def test_Partition_Duplicate_Hashes_In_One_File_Count_Once_Each_Row_Still_Classified():
    # A source file may repeat a hash; both rows must land in the same bucket.
    records = [
        (1, 2026, "nba", "a", "dup"),
        (1, 2026, "nba", "b", "dup"),
        (1, 2026, "nba", "c", "fresh"),
    ]
    new, updated = partition_by_hash(records, hash_index=4, existing_hashes={"dup"})
    assert len(new) == 1 and len(updated) == 2


def test_Summarize_Builds_Standard_Shape():
    s = summarize(new=["a"], updated=["b", "c"])
    assert s == {"total": 3, "new": 1, "updated": 2}
    assert summarize(new=[], updated=[]) == {"total": 0, "new": 0, "updated": 0}
