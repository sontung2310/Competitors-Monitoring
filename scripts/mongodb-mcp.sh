#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h}/.."
env_file="$project_dir/.env.mongodb"

if [[ ! -r "$env_file" ]]; then
  print -u2 "Missing MongoDB MCP credentials: $env_file"
  exit 1
fi

set -a
source "$env_file"
set +a

: "${MONGODB_URI:?MONGODB_URI is not set in $env_file}"
export MDB_MCP_CONNECTION_STRING="$MONGODB_URI"

exec /opt/homebrew/bin/npx -y mongodb-mcp-server@latest --readOnly "$@"
