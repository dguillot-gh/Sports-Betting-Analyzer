import os
import json
import logging
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Explicitly load .env from backend root
# __file__ is backend/services/nascar_ocr_service.py
# .env is backend/.env
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(backend_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"Loaded environment variables from {env_path}")
else:
    print(f"Warning: .env file not found at {env_path}")

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class NascarOcrService:
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        if not self.api_key:
            # Try to grab it again in case it was just loaded
            self.api_key = os.getenv("GEMINI_API_KEY")

        if not self.api_key:
            logger.warning("GEMINI_API_KEY not found. OCR features will be disabled.")
        else:
            try:
                # Using v1beta for better model compatibility, matching gemini_predictor.py
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options={'api_version': 'v1beta'}
                )
                logger.info("Gemini Client initialized successfully (v1beta)")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client: {e}")
                self.client = None

    async def extract_odds_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> List[Dict]:
        """
        Uses Gemini Flash to extract NASCAR odds from an image.
        Returns a list of dictionaries: {"driver_name": str, "market_odds": str}
        """
        if not self.client:
            logger.error("Cannot perform OCR: Gemini Client not initialized (check API Key)")
            raise Exception("OCR Service unavailable: Missing API Key configuration")

        try:
            prompt = """
            Extract NASCAR driver names and their American odds (e.g., +500, -110) from this betting image.
            Return ONLY a raw JSON list of objects with keys: "driver_name" and "market_odds".
            Example: [{"driver_name": "Kyle Larson", "market_odds": "+450"}, ...]
            Do not include markdown formatting or explanations.
            """

            # Create image part
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

            logger.info(f"Sending request to Gemini... (Image size: {len(image_bytes)} bytes)")
            
            # Using 'gemini-flash-latest' to match working gemini_predictor.py
            model_id = 'gemini-flash-latest'
            
            # Using async client (aio)
            response = await self.client.aio.models.generate_content(
                model=model_id,
                contents=[image_part, prompt],
                config=types.GenerateContentConfig(
                    safety_settings=[
                        types.SafetySetting(
                            category="HARM_CATEGORY_HARASSMENT",
                            threshold="BLOCK_NONE",
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_HATE_SPEECH",
                            threshold="BLOCK_NONE",
                        ),
                         types.SafetySetting(
                            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            threshold="BLOCK_NONE",
                        ),
                         types.SafetySetting(
                            category="HARM_CATEGORY_DANGEROUS_CONTENT",
                            threshold="BLOCK_NONE",
                        ),
                    ]
                )
            )
            
            if not response.text:
                logger.warning(f"Gemini returned empty text. Finish reason: {response.candidates[0].finish_reason if response.candidates else 'Unknown'}")
                raise Exception("AI returned no text. Image might be unclear or blocked.")

            # Clean markdown if present
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
                if text.endswith("```"):
                    text = text[:-3]
            elif text.startswith("```"):
                text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            
            try:
                data = json.loads(text.strip())
            except json.JSONDecodeError as je:
                logger.error(f"JSON Parse Error: {je}. Raw Text: {text}")
                raise Exception(f"Failed to parse AI response: {text[:100]}...")

            # Normalize keys
            results = []
            for item in data:
                # Handle potential variations in keys
                driver = item.get("driver_name") or item.get("driver") or item.get("name")
                odds = item.get("market_odds") or item.get("odds") or item.get("price")
                
                if driver and odds:
                    results.append({
                        "driver_name": driver,
                        "market_odds": str(odds),
                        "source": "ocr_upload"
                    })
            
            logger.info(f"OCR extracted {len(results)} drivers")
            if not results:
                logger.warning("OCR parsed JSON but found no valid driver entries.")
                
            return results

        except Exception as e:
            logger.error(f"OCR execution failed: {e}")
            
            # Debugging: List models to logs to see what IS available
            try:
                available_models = [m.name for m in self.client.models.list()]
                logger.info(f"Available models for this API key: {available_models}")
            except Exception as le:
                logger.error(f"Could not list models: {le}")

            # One-time fallback attempt for robustness
            if "not found" in str(e).lower() and model_id != 'gemini-pro-latest':
                try:
                    logger.info("Retrying with gemini-pro-latest...")
                    response = await self.client.aio.models.generate_content(
                        model='gemini-pro-latest',
                        contents=[image_part, prompt],
                        config=types.GenerateContentConfig(safety_settings=[])
                    )
                    if response.text:
                        # Process response (copy-pasted parsing logic for the retry)
                        text = response.text.strip()
                        if text.startswith("```json"): text = text[7:]; 
                        if text.endswith("```"): text = text[:-3]
                        data = json.loads(text.strip())
                        results = []
                        for item in data:
                            driver = item.get("driver_name") or item.get("driver") or item.get("name")
                            odds = item.get("market_odds") or item.get("odds") or item.get("price")
                            if driver and odds:
                                results.append({"driver_name": driver, "market_odds": str(odds), "source": "ocr_upload"})
                        return results
                except Exception as retry_e:
                    logger.error(f"Retry with Pro also failed: {retry_e}")

            raise Exception(f"OCR Analysis Failed: {str(e)}")

_ocr_service = None

def get_ocr_service():
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = NascarOcrService()
    return _ocr_service
