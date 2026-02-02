import logging
import asyncio
import httpx
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class SportsbookWireService:
    NBA_URL = "https://sportsbookwire.usatoday.com/nba-picks-predictions/"
    DEBUG_FILE = "sbw_debug.txt"
    
    # Comprehensive NBA Team Token Map (City, Nickname, Abbreviation)
    # Maps all variations to a unique team identifier for robust set-based matching
    TEAM_TOKENS = {
        "atlanta": "hawks", "hawks": "hawks", "atl": "hawks",
        "boston": "celtics", "celtics": "celtics", "bos": "celtics",
        "brooklyn": "nets", "nets": "nets", "bkn": "nets",
        "charlotte": "hornets", "hornets": "hornets", "cha": "hornets",
        "chicago": "bulls", "bulls": "bulls", "chi": "bulls",
        "cleveland": "cavaliers", "cavaliers": "cavaliers", "cavs": "cavaliers", "cle": "cavaliers",
        "dallas": "mavericks", "mavericks": "mavericks", "mavs": "mavericks", "dal": "mavericks",
        "denver": "nuggets", "nuggets": "nuggets", "den": "nuggets",
        "detroit": "pistons", "pistons": "pistons", "det": "pistons",
        "golden state": "warriors", "warriors": "warriors", "dubs": "warriors", "gsw": "warriors",
        "houston": "rockets", "rockets": "rockets", "hou": "rockets",
        "indiana": "pacers", "pacers": "pacers", "ind": "pacers",
        "clippers": "clippers", "clips": "clippers", "lac": "clippers", "la clippers": "clippers",
        "lakers": "lakers", "lal": "lakers", "la lakers": "lakers",
        "memphis": "grizzlies", "grizzlies": "grizzlies", "grizz": "grizzlies", "mem": "grizzlies",
        "miami": "heat", "heat": "heat", "mia": "heat",
        "milwaukee": "bucks", "bucks": "bucks", "mil": "bucks",
        "minnesota": "timberwolves", "timberwolves": "timberwolves", "wolves": "timberwolves", "min": "timberwolves",
        "new orleans": "pelicans", "pelicans": "pelicans", "pels": "pelicans", "nop": "pelicans",
        "new york": "knicks", "knicks": "knicks", "nyk": "knicks",
        "oklahoma city": "thunder", "thunder": "thunder", "okc": "thunder",
        "orlando": "magic", "magic": "magic", "orl": "magic",
        "philadelphia": "76ers", "76ers": "76ers", "sixers": "76ers", "phi": "76ers",
        "phoenix": "suns", "suns": "suns", "phx": "suns",
        "portland": "blazers", "trail blazers": "blazers", "por": "blazers",
        "sacramento": "kings", "kings": "kings", "sac": "kings",
        "san antonio": "spurs", "spurs": "spurs", "sas": "spurs",
        "toronto": "raptors", "raptors": "raptors", "tor": "raptors",
        "utah": "jazz", "jazz": "jazz", "uta": "jazz",
        "washington": "wizards", "wizards": "wizards", "was": "wizards"
    }

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.client = None
        if self.api_key:
            try:
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options={'api_version': 'v1beta'}
                )
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client in SportsbookWireService: {e}")

    def _log_debug(self, message: str):
        """Append to a local debug file and logger."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        logger.info(message)
        try:
            with open(self.DEBUG_FILE, "a") as f:
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass

    async def get_picks(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Fetches SportsbookWire picks for a specific NBA matchup.
        """
        self._log_debug(f"START GET_PICKS: {away_team} @ {home_team}")
        
        try:
            # High-fidelity browser headers to bypass Gannett's basic bot detection
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
                "Cache-Control": "max-age=0"
            }
            
            # 1. Fetch the NBA picks list page
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=headers) as client:
                self._log_debug(f"Requesting list: {self.NBA_URL}")
                response = await client.get(self.NBA_URL)
                if response.status_code != 200:
                    self._log_debug(f"List Fetch FAILED: {response.status_code}")
                    return {"status": f"HTTP Error {response.status_code}"}
                
                html_content = response.text
            
            # 2. Find the article link for the specific matchup
            article_url = self._find_article_link(html_content, home_team, away_team)
            if not article_url:
                self._log_debug(f"MATCH FAILED: No article found for {away_team} @ {home_team}")
                return {"status": "No matching article found on SBW"}

            # 3. Fetch the article content
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=headers) as client:
                self._log_debug(f"Requesting article: {article_url}")
                article_response = await client.get(article_url)
                if article_response.status_code != 200:
                    self._log_debug(f"Article Fetch FAILED: {article_response.status_code}")
                    return {"status": f"Article HTTP Error {article_response.status_code}"}
                
                article_text = article_response.text

            # 4. Extract main content
            soup = BeautifulSoup(article_text, 'html.parser')
            content_div = soup.find('div', class_='entry-content') or \
                          soup.find('div', class_='article-body') or \
                          soup.body
            
            if content_div:
                for s in content_div(["script", "style", "nav", "footer"]):
                    s.decompose()
                clean_text = content_div.get_text(separator=' ', strip=True)
            else:
                clean_text = article_text[:10000]

            self._log_debug(f"Sending {len(clean_text)} chars to Gemini for parsing.")
            
            # 5. Use Gemini to parse the picks
            picks = await self._parse_picks_with_ai(clean_text, home_team, away_team)
            if picks:
                picks["article_url"] = article_url
                picks["status"] = "Success"
                self._log_debug("Successfully parsed picks via Gemini.")
            else:
                self._log_debug("Gemini failed to return valid JSON picks.")
                picks = {"status": "Analysis parsing failed"}
            
            return picks

        except Exception as e:
            self._log_debug(f"UNHANDLED EXCEPTION: {str(e)}")
            return {"status": f"Internal Error: {str(e)}"}

    def _find_article_link(self, html: str, home: str, away: str) -> Optional[str]:
        soup = BeautifulSoup(html, 'html.parser')
        
        home_tokens = self._get_tokens(home)
        away_tokens = self._get_tokens(away)
        
        self._log_debug(f"Token Sets - Home: {home_tokens}, Away: {away_tokens}")

        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            text = a.text.lower().strip()
            
            # Broad marker: look for "odds", "picks", or "predictions"
            # USAToday uses specific patterns, but let's be flexible
            is_predictive = "odds-picks-and-predictions" in href or \
                            ("/2026/0" in href and "at" in href and "odds" in href) or \
                            ("odds" in text and "picks" in text)

            if is_predictive:
                # Order-independent matching
                match_home = any(t in href or t in text for t in home_tokens)
                match_away = any(t in href or t in text for t in away_tokens)
                
                if match_home and match_away:
                    if "story/sports/nba" in href or "/nba/" in href:
                        full_url = urljoin(self.NBA_URL, a['href'])
                        self._log_debug(f"MATCH FOUND: {full_url}")
                        return full_url
        return None

    def _get_tokens(self, team_name: str) -> List[str]:
        """Convert any team name (City, Nick, Abbr) into its set of related tokens."""
        name_lower = team_name.lower().strip()
        tokens = set(name_lower.split())
        
        # Add all tokens related to any matched team identifier
        for kw, tid in self.TEAM_TOKENS.items():
            if kw in name_lower:
                # Add all keywords for that team_id
                for k, v in self.TEAM_TOKENS.items():
                    if v == tid:
                        tokens.add(k)
        
        # Filter noise
        return [t for t in tokens if len(t) > 2 or t == 'la' or t == '76ers']

    async def _parse_picks_with_ai(self, article_text: str, home: str, away: str) -> Dict[str, Any]:
        if not self.client:
            return {}

        prompt = f"""
Extract NBA betting picks for {away} @ {home} from the following text.
Look for Moneyline, Spread, and Over/Under.

Returns JSON:
- "moneyline": {{"side": "Team/PASS", "value": "Odds", "reason": "concise rationale"}}
- "spread": {{"side": "Team +/- Points", "value": "Odds", "reason": "concise rationale"}}
- "over_under": {{"side": "Over/Under Value", "value": "Odds", "reason": "concise rationale"}}
- "summary": "One sentence takeaway"

Text:
{article_text[:8000]}
"""
        try:
            response = await self.client.aio.models.generate_content(
                model='gemini-flash-latest',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    temperature=0.0
                )
            )
            import json
            return json.loads(response.text)
        except Exception as e:
            self._log_debug(f"Gemini parsing error: {e}")
            return {}

_service = None
def get_sportsbookwire_service():
    global _service
    if _service is None:
        _service = SportsbookWireService()
    return _service
