#!/usr/bin/env python3
"""
Get a Lidl Plus refresh token without any browser automation.

Requirements: pip install requests
Usage:        python3 get-token.py
"""
import base64
import hashlib
import os
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

_AUTH_API   = "https://accounts.lidl.com"
_CLIENT_ID  = "LidlPlusNativeClient"
_REDIRECT   = "com.lidlplus.app"
_APP        = "com.lidl.eci.lidl.plus"
_APP_VER    = "13.0.0"
_OS         = "iOS"


def _pkce():
    v = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, c


def main():
    lang    = input("Language (default: de): ").strip() or "de"
    country = input("Country  (default: DE): ").strip() or "DE"

    verifier, challenge = _pkce()

    params = (
        f"client_id={_CLIENT_ID}"
        f"&response_type=code"
        f"&scope=openid%20profile%20offline_access%20lpprofile%20lpapis"
        f"&redirect_uri={_REDIRECT}%3A%2F%2Fcallback"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
        f"&Country={country}"
        f"&language={lang}-{country}"
    )
    url = f"{_AUTH_API}/connect/authorize?{params}"

    print("\n" + "="*60)
    print("Open this URL in your browser:")
    print("="*60)
    print(url)
    print("="*60)
    print("\nLog in to your Lidl Plus account.")
    print("After login the browser will show an error or blank page — that's fine.")
    print("Copy the full URL from the address bar.\n")

    pasted = input("Paste the redirect URL (or just the code= value): ").strip()

    code_match = re.search(r"[?&]code=([0-9A-Za-z_\-]+)", pasted)
    if code_match:
        code = code_match.group(1)
    elif re.fullmatch(r"[0-9A-Za-z_\-]{20,}", pasted):
        code = pasted
    else:
        sys.exit("Could not find an auth code in what you pasted.")

    print(f"\nExchanging code {code[:12]}... for tokens...")

    secret = base64.b64encode(f"{_CLIENT_ID}:secret".encode()).decode()
    resp = requests.post(
        f"{_AUTH_API}/connect/token",
        headers={
            "Authorization": f"Basic {secret}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"LidlPlus/{_APP_VER} (iPhone; {_OS} 17.0; Scale/3.00)",
        },
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  f"{_REDIRECT}://callback",
            "code_verifier": verifier,
        },
        timeout=30,
    )

    data = resp.json()
    if "refresh_token" not in data:
        sys.exit(f"Token exchange failed: {data.get('error', data)}")

    token = data["refresh_token"]
    print("\n" + "="*60)
    print("SUCCESS — refresh token:")
    print("="*60)
    print(token)
    print("="*60)
    print("\nPaste this into Home Assistant:")
    print("  Settings → Devices & Services → Lidl Plus → Configure")
    print("  or use the 'Paste refresh token' option when adding the integration.\n")


if __name__ == "__main__":
    main()
