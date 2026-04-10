#!/bin/bash
# Payback.de coupon activator
#
# First-time setup (or when session expires):
#   ./payback/payback.sh --login      Opens Firefox, you log in manually, cookies are saved
#
# Normal headless run (use in cron / Home Assistant):
#   ./payback/payback.sh              Uses saved cookies, activates all coupons, quits
#
# Debug headless run (keeps browser open on error):
#   ./payback/payback.sh --debug

cd "$(dirname "$0")/.."
source ../venv/bin/activate 2>/dev/null || source venv/bin/activate 2>/dev/null || true

if [ -f .env ]; then
  set -a; source .env; set +a
fi

python3 payback/activate.py "$@"
