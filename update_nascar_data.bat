@echo off
echo ==========================================
echo NASCAR Data Enhancement Utility
echo ==========================================
echo.
echo This script will process the .rda files in data/nascar/raw
echo and generate the enhanced .csv files with new features.
echo.

cd /d "%~dp0"

if not exist "env\Scripts\python.exe" (
    echo Error: Python environment not found at env\Scripts\python.exe
    echo Please ensure you are running this from the PythonMLService directory
    echo and that the virtual environment is set up.
    pause
    exit /b 1
)

echo Running enhancement script...
echo.
call env\Scripts\python scripts/enhance_nascar_data.py

if %errorlevel% neq 0 (
    echo.
    echo ❌ Error: The script failed with error code %errorlevel%
    pause
    exit /b %errorlevel%
)

echo.
echo ✅ Success! Data has been updated.
echo You can now retrain your models in the Blazor UI.
echo.
pause
