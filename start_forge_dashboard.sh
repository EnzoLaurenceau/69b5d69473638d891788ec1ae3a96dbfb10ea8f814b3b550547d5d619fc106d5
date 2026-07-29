#!/bin/bash
# start_forge_dashboard.sh — Start Forge Dashboard with real-time tracking
# ========================================================================
# This script:
# 1. Runs the Hermes session tracker to update dashboard data
# 2. Starts the dashboard server
# 3. Starts the session tracker in watch mode (background)
#
# Usage:
#   ./start_forge_dashboard.sh
#   # or
#   bash start_forge_dashboard.sh

set -e

FORGE_ROOT="C:/Users/Enzo/Documents/MODELS/.claude"

echo "============================================================"
echo "FORGE DASHBOARD — Starting"
echo "============================================================"
echo ""

# 1. Update dashboard data from Hermes sessions
echo "[1/3] Updating dashboard data from Hermes sessions..."
cd "$FORGE_ROOT"
python scripts/hermes_session_tracker.py --update-all
echo ""

# 2. Start session tracker in background (updates every 30s)
echo "[2/3] Starting session tracker (background, 30s interval)..."
python scripts/hermes_session_tracker.py --watch --interval 30 &
TRACKER_PID=$!
echo "  Tracker PID: $TRACKER_PID"
echo ""

# 3. Start dashboard server
echo "[3/3] Starting dashboard server on port 7777..."
echo ""
echo "============================================================"
echo "Dashboard: http://localhost:7777"
echo "Vault:     http://localhost:7777/vault.html"
echo "Tracker:   PID $TRACKER_PID (updates every 30s)"
echo "============================================================"
echo ""

# Trap to kill tracker on exit
trap "echo ''; echo 'Stopping tracker...'; kill $TRACKER_PID 2>/dev/null; exit" INT TERM

# Start server (foreground)
cd "$FORGE_ROOT/09_WEB"
python server.py
