import asyncio
import time
import os
import sys

# Add backend directory to path so scripts can find src/config etc.
backend_dir = os.path.join(os.path.dirname(__file__), "backend")
sys.path.append(backend_dir)

from scripts.nhl_importer import import_all_nhl

async def run_test():
    print("Testing NHL Importer Performance")
    start_time = time.time()
    
    # Run the NHL importer with a small subset to verify it doesn't crash and works fast
    result = await import_all_nhl(clear_existing=False, start_year=2023)
    
    end_time = time.time()
    elapsed = end_time - start_time
    print(f"Result: {result}")
    print(f"Elapsed Time: {elapsed:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(run_test())
