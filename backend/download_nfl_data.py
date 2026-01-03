import asyncio
import sys
import os

# Add current directory to path so we can import scripts
sys.path.append(os.getcwd())

from scripts.nfl_importer import download_nflverse

async def main():
    print("Starting nflverse data download...")
    files = await download_nflverse(lambda msg: print(f"[DOWNLOAD] {msg}"))
    print(f"\nSuccessfully downloaded {len(files)} files!")
    print("Files:", files)

if __name__ == "__main__":
    asyncio.run(main())
