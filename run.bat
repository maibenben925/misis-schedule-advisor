@echo off
chcp 1251 >nul 2>&1
echo ================================
echo  Schedule Advisor - MISIS
echo ================================
echo.

cd /d "%~dp0"

:: [1] venv
if not exist .venv (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create .venv
        echo Install Python 3.12+: https://python.org
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment OK
)

:: [2] dependencies
echo [2/4] Installing dependencies...
.venv\Scripts\pip.exe install -r requirements.txt -q
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

:: [3] database
echo [3/4] Database:
if exist data\schedule.db (
    echo   Found data\schedule.db
    echo.
    choice /c 12 /n /m "  [1] Use existing  [2] Rebuild from API: "
    if errorlevel 2 goto :rebuild_db
    echo   Using existing database
    goto :skip_db
)
echo   Not found - downloading from API (2-3 min)...
:rebuild_db
.venv\Scripts\python.exe pipeline\build_db.py
if errorlevel 1 (
    echo ERROR: Failed to create database
    echo Try manually: python pipeline\build_db.py
    pause
    exit /b 1
)
:skip_db

:: [4] launch
echo [4/4] Starting Streamlit...
echo.
echo   URL: http://localhost:8502
echo   Stop: Ctrl+C
echo.
.venv\Scripts\python.exe -m streamlit run src\app.py --server.headless true --server.port 8502
pause
