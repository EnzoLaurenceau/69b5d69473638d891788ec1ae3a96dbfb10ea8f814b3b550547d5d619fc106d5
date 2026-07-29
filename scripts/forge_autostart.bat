@echo off
REM ╔══════════════════════════════════════════════════════════════╗
REM ║  FORGE MEMORY WARMUP — Auto-Start (Windows Task Scheduler)  ║
REM ║  Démarre les 5 couches mémoire de La Forge au boot          ║
REM ╚══════════════════════════════════════════════════════════════╝

set FORGE_ROOT=%~dp0..
set PYTHON=C:\Users\Enzo\AppData\Local\Programs\Python\Python39\python.exe
set WARMUP_SCRIPT=%FORGE_ROOT%\scripts\forge_memory_warmup.py
set LOG_DIR=%FORGE_ROOT%\08_LOGS\boot

REM Créer le dossier de logs si absent
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Timestamp pour le log
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set D=%%c%%b%%a
for /f "tokens=1-2 delims=:." %%a in ("%time: =0%") do set T=%%a%%b

REM Attendre 30 secondes pour laisser Windows finir son init
timeout /t 30 /nobreak > nul

REM Lancer le warm-up avec logging
echo [%date% %time%] Forge Memory Warmup — starting >> "%LOG_DIR%\autostart.log"
"%PYTHON%" "%WARMUP_SCRIPT%" >> "%LOG_DIR%\autostart.log" 2>&1
echo [%date% %time%] Forge Memory Warmup — finished (exit code: %ERRORLEVEL%) >> "%LOG_DIR%\autostart.log"

REM Lancer le gardien GUI en arrière-plan (vérifie les ports après 60s)
start /B "" "%PYTHON%" "%FORGE_ROOT%\scripts\forge_autostart_gui.py" >> "%LOG_DIR%\gui_guardian.log" 2>&1
