
import os
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime
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

class GeminiPredictor:
    """
    Leverages Google Gemini 1.5 Flash for rapid sports analysis using the new google-genai SDK.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or "AIzaSyC0V9bWXsK-OsQ0Cb2yct3K3bkEd5ej5Ys"
        self.client = None
        self.model_id = 'gemini-1.5-flash'
        
        if self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")

    async def get_insight(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates a second-opinion prediction and rationale using Gemini.
        """
        if not self.client:
            return self._get_mock_insight(sport, home_team, away_team, stats)

        try:
            prompt = self._build_prompt(sport, home_team, away_team, stats)
            
            # Using the new SDK's generate_content
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=f"Give me a JSON response for this sports analysis: {prompt}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            
            quota_manager.increment()
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Gemini LLM error: {e}")
            return self._get_mock_insight(sport, home_team, away_team, stats)

    def _build_prompt(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any]) -> str:
        return f"""
        Sport: {sport}
        Matchup: {away_team} at {home_team}
        
        Available Stats (Home): {json.dumps(stats.get('home', {}), indent=2)}
        Available Stats (Away): {json.dumps(stats.get('away', {}), indent=2)}
        
        Please provide a JSON object with:
        "winner": (Predicted Team Name),
        "confidence": (0-100),
        "rationale": (Concise 2-sentence explanation),
        "key_factor": (Single most important factor/stat)
        """

    def _get_mock_insight(self, sport: str, home_team: str, away_team: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "winner": home_team,
            "confidence": 55,
            "rationale": f"Gemini insight unavailable. Traditional statistical filters suggest {home_team} holds the advantage based on home court/field efficiency.",
            "key_factor": "Home Field Advantage",
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
