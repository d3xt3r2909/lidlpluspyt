#!/usr/bin/env bash
# Wrapper: ./test_lidl_token_and_coupons.sh [--verify-only]  (from repo root)
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$ROOT/scripts/test_lidl_token_and_coupons.sh" ]; then
  echo "Missing scripts/test_lidl_token_and_coupons.sh — update this clone:"
  echo "  git remote -v"
  echo "  git pull origin main    # or: git pull <your-remote> main"
  exit 1
fi
exec "$ROOT/scripts/test_lidl_token_and_coupons.sh" "$@"
