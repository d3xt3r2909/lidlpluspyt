#!/bin/bash
# Usage:
#   ./lidl-plus.sh auth --debug          — open Firefox, log in, save token
#   ./lidl-plus.sh auth --debug --push   — same + push token to Home Assistant
#   ./lidl-plus.sh coupon                — list coupons
#   ./lidl-plus.sh coupon --all          — activate all coupons
#   ./lidl-plus.sh receipt               — list receipts
#   ./lidl-plus.sh -u other@email.com -p pass auth --debug
cd "$(dirname "$0")"
source ../venv/bin/activate 2>/dev/null || source venv/bin/activate 2>/dev/null || true

# Load defaults from .env (never committed to git)
if [ -f .env ]; then
  set -a; source .env; set +a
fi

# Parse arguments
DEBUG_FLAG=""
PUSH_TO_HA=0
EMAIL="${LIDL_EMAIL}"
PASSWORD="${LIDL_PASSWORD}"
REFRESH="${LIDL_REFRESH_TOKEN}"
CMD=""
EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug)           DEBUG_FLAG="--debug" ;;
    --push)            PUSH_TO_HA=1 ;;
    --all)             EXTRA_ARGS="--all" ;;
    -u|--user)         EMAIL="$2";    REFRESH=""; shift ;;
    -p|--password)     PASSWORD="$2"; REFRESH=""; shift ;;
    auth|coupon|receipt|loyalty) CMD="$1" ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

if [ -z "$CMD" ]; then
  echo "Usage: $0 [auth|coupon|receipt|loyalty] [--debug] [--push] [--all] [-u email] [-p pass]"
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
      # Save to .env
      if grep -q "^LIDL_REFRESH_TOKEN=" .env 2>/dev/null; then
        sed -i '' "s/^LIDL_REFRESH_TOKEN=.*/LIDL_REFRESH_TOKEN=$NEW_TOKEN/" .env
      else
        echo "LIDL_REFRESH_TOKEN=$NEW_TOKEN" >> .env
      fi
      echo ""
      echo "✓ Refresh token saved to .env"

      # Push to Home Assistant if requested or if HA_URL + HA_TOKEN are set
      if [ $PUSH_TO_HA -eq 1 ] || { [ -n "$HA_URL" ] && [ -n "$HA_TOKEN" ]; }; then
        if [ -z "$HA_URL" ] || [ -z "$HA_TOKEN" ]; then
          echo ""
          echo "  To auto-push to HA, add to .env:"
          echo "    HA_URL=http://homeassistant.local:8123"
          echo "    HA_TOKEN=<long-lived token from HA profile>"
        else
          echo ""
          echo "Pushing token to Home Assistant at ${HA_URL}..."
          HTTP_STATUS=$(curl -s -o /tmp/lidl-ha-resp.txt -w "%{http_code}" \
            -X POST "${HA_URL}/api/services/lidl_plus/set_refresh_token" \
            -H "Authorization: Bearer ${HA_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{\"refresh_token\": \"${NEW_TOKEN}\"}")
          if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "201" ]; then
            echo "✓ Home Assistant updated successfully — no restart needed."
          else
            echo "✗ HA returned HTTP $HTTP_STATUS: $(cat /tmp/lidl-ha-resp.txt)"
            echo "  Check HA_URL and HA_TOKEN in .env"
          fi
        fi
      fi
    fi
  fi
else
  if [ -z "$REFRESH" ]; then
    echo "No refresh token found in .env — run: ./lidl-plus.sh auth --debug"
    exit 1
  fi
  lidl-plus -l de -c DE -r "$REFRESH" $CMD $EXTRA_ARGS
fi
