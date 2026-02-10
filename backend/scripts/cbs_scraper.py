import asyncio
import logging
import os
import sys
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import asyncpg

# Add parent directory to path to allow import of src.config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.config import DATABASE_URL
except ImportError:
    # Fallback for local testing if src.config is not findable
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting")

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def fetch_cbs_picks(sport="NBA"):
    """Fetch the expert picks page from CBS Sports."""
    url = f"https://www.cbssports.com/{sport.lower()}/expert-picks/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    
    try:
        logger.info(f"Fetching CBS picks from {url}")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Failed to fetch CBS picks: {e}")
        return None

def parse_picks(html, sport="NBA"):
    """Parse the HTML content and extract expert picks."""
    soup = BeautifulSoup(html, 'html.parser')
    picks = []
    
    # Target date from the selected option in the calendar dropdown
    selected_date_opt = soup.find('option', selected=True, attrs={'data-date': True})
    if selected_date_opt:
        game_date_str = selected_date_opt['data-date']
        game_date = datetime.strptime(game_date_str, '%Y%m%d').date()
        logger.info(f"Detected game date from page: {game_date}")
    else:
        # Fallback to "Sports Date" logic
        game_date = (datetime.utcnow() - timedelta(hours=6)).date()
        logger.info(f"Using fallback sports date: {game_date}")

    rows = soup.find_all('div', class_='picks-tr')
    logger.info(f"Found {len(rows)} potential game rows in table.")
    
    for row in rows:
        # Each row should have game-info-team
        teams = row.find_all('div', class_='game-info-team')
        if len(teams) < 2:
            continue
            
        away_team = teams[0].find('span', class_='team').get_text(strip=True)
        home_team = teams[1].find('span', class_='team').get_text(strip=True)
        
        # Expert picks column
        expert_col = row.find('div', class_='expert-picks-col')
        if not expert_col:
            continue
            
        # Spread pick
        spread_div = expert_col.find('div', class_='expert-spread')
        spread_team = None
        spread_val = None
        if spread_div:
            # Format: "DET -5.5" or "NY +10"
            text = spread_div.get_text(strip=True)
            # Remove image alt text or logos if any
            text = text.replace('\n', ' ').strip()
            parts = text.split()
            if len(parts) >= 2:
                spread_team = parts[0]
                try:
                    # Clean the value (sometimes has extra chars)
                    val_str = re.sub(r'[^\d.-]', '', parts[1])
                    if val_str:
                        spread_val = float(val_str)
                except:
                    pass
        
        # Total pick
        ou_div = expert_col.find('div', class_='expert-ou')
        ou_pick = None
        ou_val = None
        if ou_div:
            # Format: "O 220.5" or "U 230"
            text = ou_div.get_text(strip=True)
            if 'O' in text or 'Over' in text:
                ou_pick = 'Over'
            elif 'U' in text or 'Under' in text:
                ou_pick = 'Under'
            
            # Extract number
            match = re.search(r'(\d+\.?\d*)', text)
            if match:
                ou_val = float(match.group(1))

        if spread_team or ou_pick:
            picks.append({
                'sport': sport,
                'game_date': game_date,
                'away_team': away_team,
                'home_team': home_team,
                'expert_name': 'CBS Sports Staff',
                'spread_pick_team': spread_team,
                'spread_value': spread_val,
                'total_pick': ou_pick,
                'total_value': ou_val,
                'source_url': f"https://www.cbssports.com/{sport.lower()}/expert-picks/"
            })
        
    return picks

async def save_picks(picks):
    """Save the extracted picks to the database."""
    if not picks:
        logger.warning("No picks to save.")
        return
        
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            # Ensure table exists
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS expert_picks (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    sport VARCHAR(20),
                    game_date DATE,
                    away_team VARCHAR(100),
                    home_team VARCHAR(100),
                    expert_name VARCHAR(100),
                    spread_pick_team VARCHAR(100),
                    spread_value DECIMAL(10,2),
                    total_pick VARCHAR(10),
                    total_value DECIMAL(10,2),
                    source_url TEXT,
                    UNIQUE(sport, game_date, away_team, home_team, expert_name)
                )
            """)
            
            for pick in picks:
                await conn.execute("""
                    INSERT INTO expert_picks (
                        sport, game_date, away_team, home_team, expert_name, 
                        spread_pick_team, spread_value, total_pick, total_value, source_url
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (sport, game_date, away_team, home_team, expert_name)
                    DO UPDATE SET
                        spread_pick_team = EXCLUDED.spread_pick_team,
                        spread_value = EXCLUDED.spread_value,
                        total_pick = EXCLUDED.total_pick,
                        total_value = EXCLUDED.total_value,
                        created_at = NOW()
                """, 
                pick['sport'], pick['game_date'], pick['away_team'], pick['home_team'], pick['expert_name'],
                pick['spread_pick_team'], pick['spread_value'], pick['total_pick'], pick['total_value'], pick['source_url'])
            
            logger.info(f"Successfully saved {len(picks)} expert picks.")
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"Database error while saving picks: {e}")

async def run_scraper(sport="NBA"):
    """Main entry point for the scraper."""
    html = await fetch_cbs_picks(sport)
    if html:
        picks = parse_picks(html, sport)
        if picks:
            await save_picks(picks)
            return picks
    return []

if __name__ == "__main__":
    asyncio.run(run_scraper())
