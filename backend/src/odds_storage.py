import json
import logging
import asyncio
from datetime import datetime, date
from typing import List, Dict, Any, Optional
import hashlib

logger = logging.getLogger(__name__)

class OddsStorage:
    """Utility class to store and retrieve manual analysis results from the 'results' table."""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool = None

    async def _get_conn(self):
        import asyncpg
        return await asyncpg.connect(self.database_url)

    def _compute_hash(self, data: dict) -> str:
        """Compute a hash for content deduplication."""
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    async def save_analysis(self, sport: str, home_team: str, away_team: str, analysis_data: dict):
        """Save a manual analysis result to the database."""
        conn = None
        try:
            conn = await self._get_conn()
            
            # Use sport name to find sport_id
            sport_id = await conn.fetchval("SELECT id FROM sports WHERE name = $1", sport.lower())
            if not sport_id:
                # Default to a generic sport id or handle error
                sport_id = 99 

            today = date.today()
            season = today.year
            series = "manual_cache"
            
            # Metadata includes the analysis results
            metadata = {
                "home_team": home_team,
                "away_team": away_team,
                "timestamp": datetime.now().isoformat(),
                "analysis": analysis_data,
                "sport": sport
            }
            
            # Hash includes teams and date to ensure one entry per matchup per day
            content_hash = self._compute_hash({
                "type": "manual_cache",
                "sport": sport,
                "home": home_team,
                "away": away_team,
                "date": today.isoformat()
            })

            await conn.execute(
                """INSERT INTO results (sport_id, season, series, metadata, content_hash)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (content_hash) WHERE content_hash IS NOT NULL
                   DO UPDATE SET metadata = EXCLUDED.metadata""",
                sport_id, season, series, json.dumps(metadata), content_hash
            )
            
            logger.info(f"Saved manual analysis for {away_team} @ {home_team} ({sport})")
            return True
        except Exception as e:
            logger.error(f"Error saving analysis to DB: {e}")
            return False
        finally:
            if conn:
                await conn.close()

    async def get_todays_analyses(self) -> List[Dict[str, Any]]:
        """Retrieve all manual analysis cache entries for today."""
        conn = None
        try:
            conn = await self._get_conn()
            today_str = date.today().isoformat()
            
            # Check the metadata for the timestamp or use the database's internal tracking if available.
            # In our case, we'll filters by the 'series' and then check the metadata content if needed.
            # However, simpler is just filtering by series and parsing.
            
            rows = await conn.fetch(
                "SELECT metadata FROM results WHERE series = 'manual_cache' ORDER BY id DESC LIMIT 100"
            )
            
            results = []
            today_prefix = today_str
            
            for row in rows:
                try:
                    meta = json.loads(row['metadata'])
                    # Filter for today only
                    if meta.get('timestamp', '').startswith(today_prefix):
                        results.append(meta)
                except:
                    continue
                    
            return results
        except Exception as e:
            logger.error(f"Error fetching analyses from DB: {e}")
            return []
        finally:
            if conn:
                await conn.close()

# Singleton instance helper
_storage_instance = None

def get_odds_storage():
    global _storage_instance
    if _storage_instance is None:
        from src.config import DATABASE_URL
        _storage_instance = OddsStorage(DATABASE_URL)
    return _storage_instance
