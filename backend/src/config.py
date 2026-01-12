
import os

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://sports_user:sportsbetting2024@postgres:5432/sports_betting"
)

# Gemini AI configuration
GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY", 
    "AIzaSyBWy5J4BCPPbNvmJIm_kurP_xpGxiXeprk"
)

# Application settings
USE_DATABASE = os.getenv("USE_DATABASE", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# The Odds API configuration
# Free usage up to 500 requests per month
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "4aee54c212eef472437166704a960985")
