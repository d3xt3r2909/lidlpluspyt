#!/bin/bash
# Diagnostic script — tests auth token renewal and all API endpoints
cd "$(dirname "$0")"
source ../venv/bin/activate
set -a; source .env; set +a

echo "=== Getting access token from refresh token ==="
echo "Refresh token: ${LIDL_REFRESH_TOKEN:0:10}... (length: ${#LIDL_REFRESH_TOKEN})"

python3 << PYEOF
import traceback, requests as req

try:
    from lidlplus import LidlPlusApi
    api = LidlPlusApi('de', 'DE', refresh_token='$LIDL_REFRESH_TOKEN')
    api._renew_token()
    token = api.token
    print(f"[OK] Access token obtained (length: {len(token)})")

    headers = api._default_headers()
    print(f"[OK] Headers: App-Version={headers.get('App-Version')} OS={headers.get('Operating-System')}")

    print("\n=== Testing receipts API ===")
    r = req.get("https://tickets.lidlplus.com/api/v2/DE/tickets?pageNumber=1&onlyFavorite=False",
                headers=headers, timeout=15)
    print(f"[{'OK' if r.status_code == 200 else 'FAIL'}] Receipts: HTTP {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"     Total receipts: {data.get('totalCount', '?')}")

    print("\n=== Testing coupons API ===")
    r = req.get("https://coupons.lidlplus.com/app/api/v2/promotionsList",
                headers={**headers, "Country": "DE"}, timeout=15)
    print(f"[{'OK' if r.status_code == 200 else 'FAIL'}] Coupons: HTTP {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        sections = data.get("sections", [])
        total = sum(len(s.get("promotions", [])) for s in sections)
        print(f"     Total coupons: {total}")

except Exception as e:
    print(f"[FAIL] {e}")
    traceback.print_exc()
PYEOF
