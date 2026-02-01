import logging
import asyncio
import httpx
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

class SportsbookWireService:
    BASE_URL = "https://sportsbookwire.usatoday.com/category/nba/"
    
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.client = None
        if self.api_key:
            try:
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options={'api_version': 'v1beta'}
                )
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client in SportsbookWireService: {e}")

    async def get_picks(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Fetches SportsbookWire picks for a specific NBA matchup.
        """
        try:
            # 1. Fetch the NBA list page
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                response = await client.get(self.BASE_URL)
                if response.status_code != 200:
                    logger.error(f"Failed to fetch SportsbookWire NBA page: {response.status_code}")
                    return {}
                
                html_content = response.text
            
            # 2. Find the article link for the specific matchup
            # We look for links containing both team names (or fragments)
            article_url = self._find_article_link(html_content, home_team, away_team)
            if not article_url:
                logger.info(f"No SportsbookWire article found for {away_team} @ {home_team}")
                return {}

            # 3. Fetch the article content
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                article_response = await client.get(article_url)
                if article_response.status_code != 200:
                    logger.error(f"Failed to fetch SportsbookWire article: {article_response.status_code}")
                    return {}
                
                article_text = article_response.text

            # 4. Use Gemini to parse the picks from the article text
            return await self._parse_picks_with_ai(article_text, home_team, away_team)

        except Exception as e:
            logger.error(f"Error in SportsbookWireService: {e}")
            return {}

    def _find_article_link(self, html: str, home: str, away: str) -> Optional[str]:
        # Simple heuristic: look for team names in <a> tags
        # In a real scenario, we'd use BeautifulSoup, but here we can try fragments
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        home_lower = home.lower()
        away_lower = away.lower()
        
        # Team Aliases/Short names (optional, could be improved)
        home_short = home.split()[-1].lower()
        away_short = away.split()[-1].lower()

        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.text.lower()
            
            # Article URLs usually look like ...team1-at-team2-odds-picks...
            # and contain "odds-picks-and-predictions"
            if "odds-picks-and-predictions" in href or "odds-picks-and-predictions" in text:
                if (home_short in href or home_short in text) and (away_short in href or away_short in text):
                    if "story/sports/nba" in href:
                        return href
        return None

    async def _parse_picks_with_ai(self, article_text: str, home: str, away: str) -> Dict[str, Any]:
        if not self.client:
            return {}

        prompt = f"""
Extract NBA betting picks for {away} @ {home} from the following SportsbookWire article text.
Specifically, look for recommendations for:
1. Moneyline (ML)
2. Against the Spread (ATS)
3. Over/Under (O/U)

Returns a JSON object with keys: "moneyline", "spread", "over_under", and "summary".
Each pick should include "side" (e.g., "{home}", "{away}", "Over", "Under", "PASS") and "value" (e.g., "-110", "-5.5", "224.5").
Include a brief "reason" for each pick based on the text.
If a pick is "PASS", set side to "PASS".

Article Text:
{article_text[:8000]}  # Limit text to avoid token limits
"""
        try:
            response = await self.client.aio.models.generate_content(
                model='gemini-flash-latest',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json'
                )
            )
            
            import json
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Error parsing SportsbookWire picks with AI: {e}")
            return {}

_service = None
def get_sportsbookwire_service():
    global _service
    if _service is None:
        _service = SportsbookWireService()
    return _service
