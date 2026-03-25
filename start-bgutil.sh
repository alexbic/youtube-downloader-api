#!/bin/bash

# Print POT Server banner
echo "[INFO] ======================================================================"
echo "[INFO]                    🎫  POT Server (bgutil v1.2.2)                    "
echo "[INFO] ======================================================================"
echo "[INFO]   YouTube PO Token provider for SABR bypass"
echo "[INFO]   Listening on: [::]:4416"

# Start bgutil server
# Verbose token logs are filtered out to keep output clean
cd /opt/bgutil/server
exec node build/main.js 2>&1 | stdbuf -oL grep -v -E "^(Using challenge|Generated IntegrityToken|Generating POT|poToken:|Started POT server)"
