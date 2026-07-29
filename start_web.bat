@echo off
REM ╔══════════════════════════════════════════╗
REM ║       AGENTIC OS — Web Launcher          ║
REM ║  Lance le serveur sur localhost:7777     ║
REM ╚══════════════════════════════════════════╝

cd /d %~dp0
echo.
echo  Agentic OS -- Demarrage...
echo  URL : http://localhost:7777
echo.

pip install fastapi uvicorn websockets --quiet --break-system-packages 2>nul

C:\Users\Enzo\AppData\Local\Programs\Python\Python39\python.exe 09_WEB/server.py

pause
