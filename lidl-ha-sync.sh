#!/bin/bash
# lidl-ha-sync.sh — Get a fresh Lidl Plus token and push it to Home Assistant.
#
# Usage:
#   ./lidl-ha-sync.sh                          — uses values from .env
#   ./lidl-ha-sync.sh --ha-url http://192.168.1.10:8123 --ha-token <long-lived-token>
#
# First-time setup:
#   1. In HA → Profile (bottom-left avatar) → Long-Lived Access Tokens → Create Token
#   2. Add to .env:
#        HA_URL=http://homeassistant.local:8123
#        HA_TOKEN=your_long_lived_token_here

cd "$(dirname "$0")"
source ../venv/bin/activate 2>/dev/null || source venv/bin/activate 2>/dev/null || true

# Load .env
if [ -f .env ]; then
  set -a; source .env; set +a
fi

# Parse overrides
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ha-url)   HA_URL="$2";   shift ;;
    --ha-token) HA_TOKEN="$2"; shift ;;
    --debug)    DEBUG_FLAG="--debug" ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

if [ -z "$HA_URL" ] || [ -z "$HA_TOKEN" ]; then
  echo "ERROR: HA_URL and HA_TOKEN are required."
  echo "Add them to .env or pass --ha-url / --ha-token"
  echo ""
  echo "To create a token in HA:"
  echo "  Profile (bottom-left) → Long-Lived Access Tokens → Create Token"
  exit 1
fi

echo "Step 1: Getting fresh Lidl Plus token..."

# Run the existing auth flow (browser opens, user logs in)
OUTPUT=$(lidl-plus -l de -c DE -m e \
  -u "${LIDL_EMAIL}" \
  -p "${LIDL_PASSWORD}" \
  --2fa email \
  ${DEBUG_FLAG} auth 2>&1)

echo "$OUTPUT"

# Extract token from output
NEW_TOKEN=$(echo "$OUTPUT" | grep -A1 "refresh token" | tail -1 | tr -d '[:space:]')

if [ -z "$NEW_TOKEN" ] || [ ${#NEW_TOKEN} -lt 20 ]; then
  echo ""
  echo "ERROR: Could not extract a refresh token from the output above."
  exit 1
fi

echo ""
echo "Got token: ${NEW_TOKEN:0:12}..."

# Save to .env
if grep -q "^LIDL_REFRESH_TOKEN=" .env 2>/dev/null; then
  sed -i '' "s/^LIDL_REFRESH_TOKEN=.*/LIDL_REFRESH_TOKEN=$NEW_TOKEN/" .env
else
  echo "LIDL_REFRESH_TOKEN=$NEW_TOKEN" >> .env
fi
echo "Saved to .env"

echo ""
echo "Step 2: Pushing token to Home Assistant at ${HA_URL}..."

HTTP_STATUS=$(curl -s -o /tmp/lidl-ha-sync-response.txt -w "%{http_code}" \
  -X POST "${HA_URL}/api/services/lidl_plus/set_refresh_token" \
  -H "Authorization: Bearer ${HA_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\": \"${NEW_TOKEN}\"}")

RESPONSE=$(cat /tmp/lidl-ha-sync-response.txt)

if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "201" ]; then
  echo "Done! Home Assistant updated successfully."
else
  echo "ERROR: HA returned HTTP $HTTP_STATUS"
  echo "Response: $RESPONSE"
  echo ""
  echo "Check that:"
  echo "  1. HA_URL is correct and reachable: ${HA_URL}"
  echo "  2. HA_TOKEN is a valid long-lived access token"
  echo "  3. The Lidl Plus integration is loaded in HA"
fi
