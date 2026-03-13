import asyncio
import asyncpg
from src.config import DATABASE_URL

async def run():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('ALTER TABLE import_logs ADD COLUMN IF NOT EXISTS new_rows_imported INTEGER DEFAULT 0;')
    await conn.execute('ALTER TABLE import_logs ADD COLUMN IF NOT EXISTS updated_rows_imported INTEGER DEFAULT 0;')
    await conn.execute('ALTER TABLE import_logs ADD COLUMN IF NOT EXISTS files_processed INTEGER DEFAULT 0;')
    await conn.close()
    print('DB Altered successfully.')

if __name__ == "__main__":
    asyncio.run(run())
