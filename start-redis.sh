#!/bin/bash

# Print Redis Connection banner
echo "[INFO] ======================================================================"
echo "[INFO]                        🔌  Redis Connection                       "
echo "[INFO] ======================================================================"

# Start Redis server, prefix output with [INFO] for Dokploy log level detection
redis-server --maxmemory "${REDIS_MAXMEMORY:-256mb}" --maxmemory-policy allkeys-lru --save "" --loglevel notice 2>&1 | sed -u 's/^/[INFO] /'
