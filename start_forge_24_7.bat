@echo off
REM start_forge_24_7.bat — Single 24/7 Forge Dashboard process
REM ============================================================
REM Registered as Windows scheduled task "ForgeDashboard" (ONLOGON).
REM server.py serves the dashboard on 0.0.0.0:7777 AND self-collects
REM telemetry every 5s (Hermes + Claude Code + Forge + Antigravity)
REM via forge_telemetry_daemon.ForgeTelemetryDaemon. One process = serve
REM + fresh data. No separate tracker/daemon needed.
cd /d "C:\Users\Enzo\Documents\MODELS\.claude\09_WEB"
"C:\Python313\python.exe" server.py
