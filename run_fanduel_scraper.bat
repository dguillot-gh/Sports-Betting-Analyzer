@echo off
echo ==========================================
echo   NASCAR Odds Scraper Helper
echo ==========================================

echo Checking for Python...
python --version
if %errorlevel% neq 0 (
    echo Python is not found! Please install Python 3.10+ and add to PATH.
    pause
    exit /b
)

echo.
echo Installing dependencies (selenium, undetected-chromedriver)...
pip install selenium undetected-chromedriver

echo.
echo Running FanDuel Scraper...
echo Note: This will open a Chrome window. Do not close it immediately.
python backend/scripts/fanduel_selenium.py

echo.
echo Done! Check fanduel_odds.json if successful.
pause
