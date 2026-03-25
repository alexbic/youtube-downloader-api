#!/bin/bash
# Wait until orchestrator declares system ready, then start gunicorn
# No output - completely silent wait
set -euo pipefail

READY_FILE="/tmp/system-ready"
TIMEOUT="120"
ELAPSED=0

while [ $ELAPSED -lt $TIMEOUT ]; do
  if [ -f "$READY_FILE" ]; then
    # --preload loads app once in master, then forks to workers
    exec gunicorn -c gunicorn_config.py --preload --bind 0.0.0.0:5000 --workers 2 --timeout 600 app:app
  fi
  sleep 1
  ELAPSED=$((ELAPSED+1))
done

exec gunicorn -c gunicorn_config.py --preload --bind 0.0.0.0:5000 --workers 2 --timeout 600 app:app
