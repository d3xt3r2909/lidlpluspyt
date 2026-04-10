#!/bin/bash
# Usage:
#   ./lidl-plus.sh auth           — get/renew refresh token
#   ./lidl-plus.sh auth --debug   — open browser for manual login
#   ./lidl-plus.sh coupon         — list coupons
#   ./lidl-plus.sh coupon --all   — activate all coupons
#   ./lidl-plus.sh receipt        — list receipts
#   ./lidl-plus.sh -u other@email.com -p pass auth --debug
cd "$(dirname "$0")"
source ../venv/bin/activate

# Load defaults from .env (never committed to git)
if [ -f .env ]; then
  set -a; source .env; set +a
fi

# Parse arguments
DEBUG_FLAG=""
EMAIL="${LIDL_EMAIL}"
PASSWORD="${LIDL_PASSWORD}"
REFRESH="${LIDL_REFRESH_TOKEN}"
CMD=""
EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug) DEBUG_FLAG="--debug" ;;
    --all)   EXTRA_ARGS="--all" ;;
    -u|--user)     EMAIL="$2";    REFRESH=""; shift ;;
    -p|--password) PASSWORD="$2"; REFRESH=""; shift ;;
    auth|coupon|receipt|loyalty) CMD="$1" ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

if [ -z "$CMD" ]; then
  echo "Usage: $0 [auth|coupon|receipt|loyalty] [--debug] [--all] [-u email] [-p pass]"
  exit 1
fi

if [[ "$CMD" == "auth" ]]; then
  if [ -n "$REFRESH" ] && [ -z "$DEBUG_FLAG" ]; then
    lidl-plus -l de -c DE -r "$REFRESH" auth
  else
    OUTPUT=$(lidl-plus -l de -c DE -m e -u "$EMAIL" -p "$PASSWORD" --2fa email $DEBUG_FLAG auth)
    echo "$OUTPUT"
    NEW_TOKEN=$(echo "$OUTPUT" | grep -A1 "refresh token" | tail -1 | tr -d '[:space:]')
    if [ -n "$NEW_TOKEN" ] && [ ${#NEW_TOKEN} -gt 20 ]; then
      sed -i '' "s/^LIDL_REFRESH_TOKEN=.*/LIDL_REFRESH_TOKEN=$NEW_TOKEN/" .env
      echo ""
      echo "✓ Refresh token saved to .env"
    fi
  fi
else
  if [ -z "$REFRESH" ]; then
    echo "No refresh token found in .env — run: ./lidl-plus.sh auth --debug"
    exit 1
  fi
  lidl-plus -l de -c DE -r "$REFRESH" $CMD $EXTRA_ARGS
fi
