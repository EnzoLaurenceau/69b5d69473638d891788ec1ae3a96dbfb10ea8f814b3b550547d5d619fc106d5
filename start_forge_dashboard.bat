@echo off
REM start_forge_dashboard.bat — Start Forge Dashboard with real-time tracking
REM ==========================================================================
REM This script:
REM 1. Runs the Hermes session tracker to update dashboard data
REM 2. Starts the dashboard server
REM 3. Starts the session tracker in watch mode (background)
REM
REM Usage:
REM   start_forge_dashboard.bat

setlocal enabledelayedexpansion

set FORGE_ROOT=C:\Users\Enzo\Documents\MODELS\.claude

echo ============================================================
echo FORGE DASHBOARD — Starting
echo ============================================================
echo.

REM 1. Update dashboard data from Hermes sessions
echo [1/3] Updating dashboard data from Hermes sessions...
cd /d "%FORGE_ROOT%"
python scripts\hermes_session_tracker.py --update-all
echo.

REM 2. Start session tracker in background (updates every 3s)
echo [2/3] Starting session tracker (background, 3s interval)...
start /b python scripts\hermes_session_tracker.py --watch --interval 3
echo   Tracker started in background
echo.

REM 3. Start dashboard server
echo [3/3] Starting dashboard server on port 7777...
echo.
echo ============================================================
echo Dashboard: http://localhost:7777
echo Vault:     http://localhost:7777/vault.html
echo Tracker:   Running in background (updates every 3s)
echo ============================================================
echo.

REM Start server (foreground)
cd /d "%FORGE_ROOT%\09_WEB"
python server.py
