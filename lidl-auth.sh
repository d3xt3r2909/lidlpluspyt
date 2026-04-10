#!/bin/bash
# Usage:
#   ./lidl-auth.sh                        — use saved refresh token (instant)
#   ./lidl-auth.sh --debug                — open browser for manual login
#   ./lidl-auth.sh -u other@email.com -p pass --debug
#   ./lidl-auth.sh -u other@email.com -p pass
cd "$(dirname "$0")"
source ../venv/bin/activate

# Load defaults from .env (never committed to git)
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Parse arguments
DEBUG_FLAG=""
EMAIL="${LIDL_EMAIL}"
PASSWORD="${LIDL_PASSWORD}"
REFRESH="${LIDL_REFRESH_TOKEN}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug) DEBUG_FLAG="--debug"; REFRESH="" ;;
    -u|--user) EMAIL="$2"; REFRESH=""; shift ;;
    -p|--password) PASSWORD="$2"; REFRESH=""; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

if [ -n "$REFRESH" ]; then
  lidl-plus -l de -c DE -r "$REFRESH" auth
else
  lidl-plus -l de -c DE -m e -u "$EMAIL" -p "$PASSWORD" --2fa email $DEBUG_FLAG auth
fi
