@echo off
REM Double-click this file to run scraping + Claude Batch enrichment.
REM This DOES call the Anthropic API and will cost money -- make sure
REM ANTHROPIC_API_KEY is set in your .env before running this one.
cd /d "%~dp0"

if not exist ".env" (
    echo ================================================
    echo  ERROR: .env file not found.
    echo  Copy .env.example to .env and set MONGODB_URI + ANTHROPIC_API_KEY first.
    echo ================================================
    pause
    exit /b 1
)

echo ================================================
echo  Adhbhutgyaan Pipeline - Full Run (scrape + enrich)
echo ================================================
echo.

python scripts\run_local_pipeline.py

echo.
echo ================================================
echo  Done. Check the output above for results.
echo ================================================
pause
