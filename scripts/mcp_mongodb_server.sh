#!/usr/bin/env bash
# Launches the official MongoDB MCP server (mongodb-mcp-server) for this
# project, building its connection string from DATABASE_HOST/DATABASE_NAME/
# DATABASE_USERNAME/DATABASE_PASSWORD in .env at process start. Never echoes
# the resolved connection string.
set -euo pipefail

ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${DATABASE_HOST:?DATABASE_HOST is not set in .env}"
: "${DATABASE_NAME:?DATABASE_NAME is not set in .env}"
: "${DATABASE_USERNAME:?DATABASE_USERNAME is not set in .env}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD is not set in .env}"

urlencode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

ENCODED_USER=$(urlencode "$DATABASE_USERNAME")
ENCODED_PASS=$(urlencode "$DATABASE_PASSWORD")

export MDB_MCP_CONNECTION_STRING="mongodb+srv://${ENCODED_USER}:${ENCODED_PASS}@${DATABASE_HOST}/${DATABASE_NAME}?retryWrites=true&w=majority"
export MDB_MCP_READ_ONLY="true"

exec npx -y mongodb-mcp-server
