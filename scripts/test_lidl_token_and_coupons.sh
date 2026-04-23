#!/usr/bin/env bash
# Test Lidl Plus CLI before touching Home Assistant:
#   1) Verify refresh token works (fetch coupons from API).
#   2) Activate all currently valid coupons.
#
# Usage (from repo root):
#   ./scripts/test_lidl_token_and_coupons.sh
#   ./scripts/test_lidl_token_and_coupons.sh --verify-only   # step 1 only
#
# Prerequisites:
#   - .env with LIDL_REFRESH_TOKEN (and matching LIDL_COUNTRY / LIDL_LANGUAGE if not DE/de)
#   - If you have no token yet: ./lidl-auth.sh --debug   then paste token into .env

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -d "$ROOT/venv" ]; then
  # shellcheck source=/dev/null
  source "$ROOT/venv/bin/activate"
elif [ -d "$ROOT/../venv" ]; then
  # shellcheck source=/dev/null
  source "$ROOT/../venv/bin/activate"
else
  echo "ERROR: No venv found at $ROOT/venv or $ROOT/../venv"
  echo "Create one: python3 -m venv venv && source venv/bin/activate && pip install -e ."
  exit 1
fi

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi

CLI_LANG="${LIDL_LANGUAGE:-de}"
CLI_COUNTRY="${LIDL_COUNTRY:-DE}"
VERIFY_ONLY=0
for arg in "$@"; do
  if [ "$arg" = "--verify-only" ]; then
    VERIFY_ONLY=1
  fi
done

if [ -z "${LIDL_REFRESH_TOKEN:-}" ]; then
  echo "ERROR: LIDL_REFRESH_TOKEN is empty in .env"
  echo "Run:  ./lidl-auth.sh --debug"
  echo "Then add the printed token to .env as LIDL_REFRESH_TOKEN=..."
  exit 1
fi

export REPO_ROOT="$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export TEST_LANG="$CLI_LANG"
export TEST_COUNTRY="$CLI_COUNTRY"

echo "== Step 1: Verify refresh token (fetch coupons, $CLI_LANG / $CLI_COUNTRY) =="
python3 <<'PY'
import os, sys
sys.path.insert(0, os.environ.get("REPO_ROOT", "."))
from lidlplus import LidlPlusApi
from lidlplus.exceptions import LoginError, WebBrowserException

lang = os.environ.get("TEST_LANG", "de")
country = os.environ.get("TEST_COUNTRY", "DE")
token = (os.environ.get("LIDL_REFRESH_TOKEN") or "").strip()
if not token:
    print("ERROR: LIDL_REFRESH_TOKEN missing")
    sys.exit(1)
try:
    api = LidlPlusApi(lang, country, token)
    data = api.coupons()
except (LoginError, WebBrowserException, Exception) as e:
    print(f"ERROR: Token invalid or API failed: {e}")
    sys.exit(1)

sections = data.get("sections") or []
total = 0
for s in sections:
    promos = s.get("promotions") or s.get("coupons") or []
    if isinstance(promos, dict):
        promos = list(promos.values()) if promos else []
    total += len(promos)
print(f"OK — token works. Sections: {len(sections)}, promotions (approx): {total}")
PY

echo ""
if [ "$VERIFY_ONLY" -eq 1 ]; then
  echo "(--verify-only) Skipping activation."
  exit 0
fi

echo "== Step 2: Activate all valid coupons (same token) =="
lidl-plus -l "$CLI_LANG" -c "$CLI_COUNTRY" -r "$LIDL_REFRESH_TOKEN" coupon --all

echo ""
echo "Done. If .env LIDL_REFRESH_TOKEN is stale, run ./lidl-auth.sh --debug again."
