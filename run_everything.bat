@echo off
REM Double-click this to run the WHOLE pipeline (discovery -> scrape ->
REM prefilter -> enrich -> transcripts -> gap analysis), in order, with
REM automatic retry if a step fails. Runs once and exits.
REM
REM To loop it forever (repeat every 6 hours), open this file in Notepad
REM and change the last line to add:  --repeat-every-hours 6
REM
REM Needs .env set up first (MONGODB_URI at minimum).
cd /d "%~dp0"

if not exist ".env" (
    echo ================================================
    echo  ERROR: .env file not found.
    echo  Copy .env.example to .env and set MONGODB_URI first.
    echo ================================================
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo ================================================
    echo  ERROR: venv not found. Run these once first:
    echo    python -m venv venv
    echo    venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo ================================================
    pause
    exit /b 1
)

echo ================================================
echo  Adhbhutgyaan Pipeline - Full Automated Run
echo  (discovery, scrape, prefilter, enrich, transcripts, gap analysis)
echo ================================================
echo.

venv\Scripts\python.exe scripts\run_everything.py

echo.
echo ================================================
echo  Done. Full details saved under logs\
echo ================================================
pause
