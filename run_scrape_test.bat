@echo off
REM Double-click this file to run a scraping-only test (no Claude API cost).
REM Works regardless of where you double-click from -- always runs from
REM this file's own folder.
cd /d "%~dp0"

if not exist ".env" (
    echo ================================================
    echo  ERROR: .env file not found.
    echo  Copy .env.example to .env and set MONGODB_URI first.
    echo ================================================
    pause
    exit /b 1
)

echo ================================================
echo  Adhbhutgyaan Pipeline - Scrape Test (no enrich)
echo ================================================
echo.

python scripts\run_local_pipeline.py --skip-enrich

echo.
echo ================================================
echo  Done. Check the output above for results.
echo ================================================
pause
