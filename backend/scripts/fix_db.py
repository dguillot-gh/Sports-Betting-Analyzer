import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from src.database import execute
import logging

logging.basicConfig(level=logging.INFO)

async def run_migration():
    migration_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'db', 'migrations', '05_model_performance.sql'))
    with open(migration_path, 'r') as file:
        sql = file.read()
    
    print("Running migration to create model_performance...")
    try:
        await execute(sql)
        print("Successfully created model_performance table!")
    except Exception as e:
        print(f"Error creating table: {e}")

if __name__ == "__main__":
    asyncio.run(run_migration())
