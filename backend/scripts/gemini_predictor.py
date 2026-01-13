
import os
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime

# Monkeypatch for Python 3.13 compatibility with google-genai
import collections
import collections.abc
for name in ['MutableSet', 'MutableMapping', 'Mapping', 'Iterable', 'Callable']:
    if not hasattr(collections, name):
        setattr(collections, name, getattr(collections.abc, name))

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class QuotaManager:
    """Simple tracker for Gemini free tier usage."""
    def __init__(self):
        self.daily_limit = 1500  # Default Gemini 1.5 Flash free tier daily limit
        self.requests_today = 0
        self.last_reset = datetime.now().date()
        self.storage_file = "gemini_usage.json"
        self._load()

    def _load(self):
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, "r") as f:
                    data = json.load(f)
                    if data.get("date") == str(datetime.now().date()):
                        self.requests_today = data.get("count", 0)
                    else:
                        self.requests_today = 0
            except:
                self.requests_today = 0

    def _save(self):
        try:
            with open(self.storage_file, "w") as f:
                json.dump({"date": str(datetime.now().date()), "count": self.requests_today}, f)
        except:
            pass

    def increment(self):
        self.requests_today += 1
        self._save()

    def get_status(self):
        return {
            "used": self.requests_today,
            "limit": self.daily_limit,
            "remaining": max(0, self.daily_limit - self.requests_today)
        }

quota_manager = QuotaManager()

from src.config import GEMINI_API_KEY

class GeminiPredictor:
    """
    Leverages Google Gemini 1.5 Flash for rapid sports analysis using the new google-genai SDK.
    """
    def __init__(self, api_key: Optional[str] = None):
        # Prioritize passed key, then centralized config
        self.api_key = api_key or GEMINI_API_KEY
        self.client = None
        self.model_id = 'gemini-flash-latest'
        
        if self.api_key:
            try:
                # Use v1beta for better model compatibility
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options={'api_version': 'v1beta'}
                )
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")

    async def get_insight(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any], game_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates a second-opinion prediction and rationale using Gemini.
        """
        if not self.client:
            return self._get_mock_insight(sport, home_team, away_team, stats)

        try:
            prompt = self._build_prompt(sport, home_team, away_team, stats, game_date)
            
            # Configure tools for Google Search grounding to get real-time info (like injuries)
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )

            # Simplified generate_content call (using async)
            response = await self.client.aio.models.generate_content(
                model=self.model_id,
                contents=f"Respond strictly in JSON format. Today is {datetime.now().strftime('%Y-%m-%d')}. Sports analysis: {prompt}",
                config=config
            )
            
            quota_manager.increment()
            
            # Robust JSON parsing (strip markdown backticks if present)
            text = response.text.strip()
            if text.startswith("```"):
                # Find first { and last }
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1:
                    text = text[start:end+1]
            
            return json.loads(text)
        except Exception as e:
            logger.error(f"Gemini LLM error: {e}")
            return self._get_mock_insight(sport, home_team, away_team, stats)

    def _build_prompt(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any], game_date: Optional[str] = None) -> str:
        date_str = game_date or datetime.now().strftime("%Y-%m-%d")
        sport_upper = sport.upper()
        
        # 1. Extract Betting Context if available from stats
        home_metrics = stats.get('home', {})
        away_metrics = stats.get('away', {})
        
        ml_home = stats.get('home_ml') or home_metrics.get('moneyline') or "N/A"
        ml_away = stats.get('away_ml') or away_metrics.get('moneyline') or "N/A"
        spread = stats.get('spread') or home_metrics.get('spread') or "N/A"
        ov_un = stats.get('over_under') or "N/A"

        # 2. Sport-Specific Priorities
        priorities = ""
        if sport_upper == "NBA":
            priorities = """
            - Pace (possessions per game) and how it affects scoring volume
            - Offensive rating vs defensive rating mismatches
            - Usage rate changes caused by injuries or rotation absences
            - Half-court offense vs transition efficiency
            - Bench depth, rotation compression, and minute distribution
            """
        elif sport_upper == "NFL":
            priorities = """
            - Quarterback availability and protection
            - Offensive line and secondary injuries
            - Run/pass balance and expected game script
            - Red zone efficiency and turnover volatility
            - Weather conditions and outdoor stadium impact when applicable
            """
        elif sport_upper == "NASCAR":
            priorities = """
            - Track type and historical performance at this venue
            - Driver and team form over recent races
            - Qualifying position and starting grid advantage
            - Pit crew efficiency and strategic tendencies
            - Long-run speed vs short-run speed
            - Caution probability and stage racing dynamics
            """
        elif sport_upper == "NCAAB":
            priorities = """
            - Adjusted tempo and possession control
            - Offensive execution vs defensive pressure
            - Experience vs youth in lineups
            - Home-court advantage intensity
            - Coaching style, rotation depth, and substitution patterns
            - Turnover rate and free-throw reliance
            """
        elif "BASEBALL" in sport_upper:
            priorities = """
            - Starting pitcher availability, pitch limits, and recent workload
            - Bullpen depth and recent usage
            - Offensive splits (home vs away)
            - Defensive efficiency and error rates
            - Weather conditions (wind, temperature)
            - Ballpark run environment and dimensions
            """

        # 3. Master Prompt Template
        master_prompt = f"""
        You are a professional sports betting analyst explaining market expectations. Analyze the following matchup:
        League: {sport_upper}
        Game Date: {date_str}
        Away Team/Driver: {away_team}
        Home Team/Track: {home_team}
        Moneyline: {away_team} {ml_away}, {home_team} {ml_home}
        Spread: {spread}
        Over/Under: {ov_un}

        Prioritize these factors for {sport_upper}:
        {priorities}

        Explain why the market favors one team over the other and why the projected Over/Under is set at this number.
        Your analysis MUST include:
        1. Market Rationale (Bookmaker perspective, win probability)
        2. Injury Impact (Critical: Search for LATEST injury reports for {date_str}. Mention specific key players by name and their specific injury, e.g., 'Cade Cunningham (wrist)'). 
        3. Matchup Dynamics (Structural advantages, schematic impact of injuries)
        4. Game Environment & Total (O/U explanation, pace, tendencies)
        5. Situational Factors (Home/Away, rest, travel, recent form)
        6. Summary (Concise tie-together explaining why this team is favored and why the total is priced where it is)

        Response Guidelines:
        - Avoid generic commentary. Use realistic on-field/on-court factors.
        - Ensure injuries are current for {date_str}, NOT old data.
        - **FORMATTING**: Use Markdown extensively for readability. Use '###' for section headers, bullet points for lists, and **bold text** for player names or key metrics. 
        - **SPACING**: Use double newlines (\\n\\n) between sections to avoid a "wall of text".
        """

        # 4. JSON Schema instruction
        prompt_metrics = """
        "winner": (Predicted Team Name or Driver Name),
        "confidence": (0-100),
        "rationale": (Provide the full detailed 6-point analysis here. Use ### headers for each point, bullet points, and bold emphasis. Format as a single string containing valid Markdown with double newlines between sections),
        "key_factor": (The single most important factor, e.g., 'Cade Cunningham Injury')
        """
        
        return f"{master_prompt}\n\nPlease provide a JSON object with:\n{prompt_metrics}"

    def _get_mock_insight(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        winner = home_team
        reason = f"Traditional statistical filters suggest {home_team} holds the advantage based on home court/field efficiency."
        
        if sport.lower() == "nascar":
            # For NASCAR, "winner" is actually just an endorsement of the driver's performance
            winner = away_team # Driver name
            reason = f"Historical metrics at {home_team} indicate {away_team} is a strong contender for a top finish."
            
        return {
            "winner": winner,
            "confidence": 55,
            "rationale": f"Gemini insight unavailable. {reason}",
            "key_factor": "Historical Trend",
            "is_mock": True
        }

_instance = None
def get_gemini_predictor():
    global _instance
    if _instance is None:
        _instance = GeminiPredictor()
    return _instance

def get_quota_status():
    return quota_manager.get_status()
