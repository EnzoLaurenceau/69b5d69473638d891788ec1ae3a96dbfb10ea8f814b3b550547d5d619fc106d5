@echo off
REM ====================================================================
REM Claude Session Watchdog Starter
REM ====================================================================
REM This script starts the Claude Session Watchdog daemon in the background.
REM 
REM To add this to Windows Task Scheduler to run at logon:
REM 1. Open Task Scheduler (taskschd.msc)
REM 2. Click "Create Task..." (not Basic Task)
REM 3. General tab: Name it "Claude Session Watchdog", check "Run whether user is logged on or not"
REM 4. Triggers tab: New -> Begin the task: "At log on"
REM 5. Actions tab: New -> Action: "Start a program" -> Program/script: C:\Users\Enzo\Documents\MODELS\.claude\start_session_watchdog.bat
REM 6. Conditions tab: Uncheck "Start the task only if the computer is on AC power"
REM ====================================================================

set SCRIPT_DIR=%~dp0
set SCRIPT_PATH=%SCRIPT_DIR%scripts\claude_session_watchdog.py

echo Starting Claude Session Watchdog...
start /B pythonw "%SCRIPT_PATH%" --daemon

echo Watchdog started in background.
echo Logs can be found at: %SCRIPT_DIR%05_STATE\session_watchdog.log
exit /b 0
