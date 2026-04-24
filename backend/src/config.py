
import os
from pathlib import Path

# Load .env file if it exists (for local development)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, rely on system env vars

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"
)

# Gemini AI configuration (REQUIRED - no default)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    import logging
    logging.warning("GEMINI_API_KEY not set - AI features will be disabled")

# Application settings
USE_DATABASE = os.getenv("USE_DATABASE", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# The Odds API configuration (REQUIRED for live odds - no default)
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
if not ODDS_API_KEY:
    import logging
    logging.warning("ODDS_API_KEY not set - live odds features will be disabled")

# Groq AI (optional, for faster LLM)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# College Football Data API (required for CFB features)
COLLEGE_FOOTBALL_API_KEY = os.getenv("COLLEGE_FOOTBALL_API_KEY", "")
if not COLLEGE_FOOTBALL_API_KEY:
    import logging
    logging.warning("COLLEGE_FOOTBALL_API_KEY not set - College Football features will be disabled")

# Web Push (VAPID) — generate keys with: python -m scripts.generate_vapid_keys
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "")

# Firebase Cloud Messaging — path to the service account JSON file
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")

# SMTP Email configuration — for import report emails
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO", "")

