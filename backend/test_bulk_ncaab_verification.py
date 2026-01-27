import asyncio
import logging
import json
from scripts.college_baseball_importer import run_college_baseball_import

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_bulk_import():
    """
    Test bulk import for 2024 season (all divisions).
    """
    print("Starting Bulk College Baseball Import Test...")
    
    # Run bulk import (division=0)
    # We use source='python' for speed in this test if available, or 'auto'
    result = await run_college_baseball_import(division=0, year=2024, source="auto")
    
    print("\n--- Import Results ---")
    print(f"Success: {result.get('success')}")
    print(f"Divisions Tried: {result.get('divisions')}")
    print(f"Total Teams Imported: {result.get('total_teams')}")
    print(f"Synced to DB: {result.get('synced_to_db')}")
    
    if not result.get("success"):
        print(f"Error: {result.get('db_error') or 'Unknown error'}")
        
    # Check division breakdown
    for div, res in result.get("results_per_division", {}).items():
        status = "Success" if res.get("success") else "Failed"
        teams = res.get("python", {}).get("total_teams", 0) or res.get("r", {}).get("total_teams", 0)
        print(f"Division {div}: {status} ({teams} teams)")

if __name__ == "__main__":
    asyncio.run(test_bulk_import())
