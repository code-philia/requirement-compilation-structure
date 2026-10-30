#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

echo "[deploy] Installing frontend and backend workspace dependencies"
npm install --include=dev --include=optional --no-audit --no-fund

echo "[deploy] Building frontend and backend"
npm run build

# The server initializes the database and uses the PORT supplied by the Runner.
echo "[deploy] Starting application"
exec npm run start
