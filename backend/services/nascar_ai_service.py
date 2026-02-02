import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from google import genai
from google.genai import types
from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

class NascarAiService:
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
                logger.error(f"Failed to initialize Gemini Client in NascarAiService: {e}")

    async def get_race_analysis(self, race_details: Dict[str, Any], drivers: List[Dict[str, Any]]) -> str:
        """
        Performs AI analysis of a whole NASCAR race field based on the user's strict workflow.
        """
        if not self.client:
            return "AI Analysis unavailable: Missing API Key."

        try:
            # Prepare data summary for the prompt
            driver_summary = ""
            for d in drivers:
                name = d.get("driver_name", "Unknown")
                prob = d.get("win_probability", 0)
                finish = d.get("projected_finish", 0)
                odds = d.get("market_odds", "N/A")
                conf = d.get("confidence", "Medium")
                driver_summary += f"- {name}: Prob {prob*100:.1f}%, Proj Finish {finish:.1f}, Odds {odds}, XGBoost Conf: {conf}\n"

            prompt = f"""
You are analyzing a NASCAR race using provided odds and model outputs.

**Race Context:**
- Series: {race_details.get('series', 'NASCAR Cup Series')}
- Track: {race_details.get('track', 'Unknown Track')}
- Track Type: {race_details.get('track_type', 'Standard')}
- Date: {race_details.get('date', datetime.now().strftime('%Y-%m-%d'))}

**Data (XGBoost Predictions vs Betting Market):**
{driver_summary}

**Follow this workflow strictly:**
1. Review the odds and model outputs together.
2. Identify where the XGBoost model disagrees with the betting market.
3. Determine which bets offer the best value based on that disagreement.
4. Account for NASCAR-specific factors such as track type, race length, and variance.
5. Recommend the strongest betting options.
6. Explain the reasoning clearly and practically.
7. Call out risks, volatility, or reasons to avoid certain bets.

**Guidelines:**
- You MAY give betting advice.
- Favor clarity over verbosity.
- Do not invent data or assumptions.
- Do not explain how models work.
- Focus on actionable insights, not disclaimers.

**Output Format:**
Provide a short list of recommended bets with:
- Bet type
- Odds
- Confidence level
- Brief explanation
"""

            logger.info(f"Requesting full race analysis for {race_details.get('track')}...")
            
            response = await self.client.aio.models.generate_content(
                model='gemini-flash-latest',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    top_p=0.95,
                )
            )
            
            if not response.text:
                return "AI returned an empty analysis. Please try again."

            return response.text.strip()

        except Exception as e:
            logger.error(f"NASCAR AI Analysis failed: {e}")
            return f"Error performing analysis: {str(e)}"

# Singleton
_service = None
def get_nascar_ai_service():
    global _service
    if _service is None:
        _service = NascarAiService()
    return _service
