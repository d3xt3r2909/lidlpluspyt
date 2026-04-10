#!/bin/bash
# Usage:
#   ./lidl-auth.sh          — use saved refresh token (instant, no browser)
#   ./lidl-auth.sh --debug  — open browser for manual login
cd "$(dirname "$0")"
source ../venv/bin/activate

# Load credentials from .env (never committed to git)
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

DEBUG_FLAG=""
if [[ "$1" == "--debug" ]]; then
  DEBUG_FLAG="--debug"
fi

if [ -n "$LIDL_REFRESH_TOKEN" ] && [ -z "$DEBUG_FLAG" ]; then
  lidl-plus -l de -c DE -r "$LIDL_REFRESH_TOKEN" auth
else
  lidl-plus -l de -c DE -m e -u "$LIDL_EMAIL" -p "$LIDL_PASSWORD" --2fa email $DEBUG_FLAG auth
fi
