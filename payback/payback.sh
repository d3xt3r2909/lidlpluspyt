#!/bin/bash
# Payback.de coupon activator
#
# Usage:
#   ./payback/payback.sh           — headless, uses .env credentials
#   ./payback/payback.sh --debug   — opens Firefox for manual interaction
#   ./payback/payback.sh -u email -p pass --debug

cd "$(dirname "$0")/.."
source ../venv/bin/activate 2>/dev/null || source venv/bin/activate 2>/dev/null || true

if [ -f .env ]; then
  set -a; source .env; set +a
fi

python3 payback/activate.py "$@"
