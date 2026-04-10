"""Lidl Plus API client — no browser dependency, refresh-token based."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta

import requests
from requests import Session

_AUTH_API = "https://accounts.lidl.com"
_TICKET_API = "https://tickets.lidlplus.com/api/v2"
_COUPONS_API = "https://coupons.lidlplus.com/app/api"
_CLIENT_ID = "LidlPlusNativeClient"
_APP = "com.lidl.eci.lidl.plus"
_OS = "iOS"
_APP_VERSION = "13.0.0"
_TIMEOUT = 30


class LidlAuthError(Exception):
    """Raised when authentication fails (expired/invalid refresh token)."""


# ---------------------------------------------------------------------------
# Standalone headless login (no browser needed)
# ---------------------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _exchange_code(code: str, verifier: str) -> str:
    """Exchange an OAuth auth code + PKCE verifier for a refresh token."""
    secret = base64.b64encode(f"{_CLIENT_ID}:secret".encode()).decode()
    resp = requests.post(
        f"{_AUTH_API}/connect/token",
        headers={
            "Authorization": f"Basic {secret}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{_APP}://callback",
            "code_verifier": verifier,
        },
        timeout=_TIMEOUT,
    )
    data = resp.json()
    if "refresh_token" not in data:
        raise LidlAuthError(f"Code exchange failed: {data.get('error', data)}")
    return data["refresh_token"]


def login_with_credentials(language: str, country: str, email: str, password: str) -> str:
    """
    Attempt a headless (no browser) PKCE login with Lidl credentials.

    Returns the refresh token on success.
    Raises LidlAuthError if Lidl enforces CAPTCHA or login fails.
    """
    language = language.lower()
    country = country.upper()
    verifier, challenge = _pkce_pair()

    session = Session()
    session.headers.update({
        "User-Agent": f"LidlPlus/{_APP_VERSION} (iPhone; {_OS} 17.0; Scale/3.00)",
        "Accept-Language": f"{language}-{country}",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    # Step 1: GET /connect/authorize → follows redirect to login page
    params = {
        "client_id": _CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile offline_access lpprofile lpapis",
        "redirect_uri": f"{_APP}://callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "Country": country,
        "language": f"{language}-{country}",
    }
    r = session.get(
        f"{_AUTH_API}/connect/authorize",
        params=params,
        allow_redirects=True,
        timeout=_TIMEOUT,
    )

    # Step 2: Extract CSRF token from the login page HTML
    csrf_match = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text
    )
    if not csrf_match:
        raise LidlAuthError(
            "Could not extract CSRF token — Lidl may be enforcing CAPTCHA"
        )
    csrf_token = csrf_match.group(1)
    login_url = r.url  # the actual login page URL after redirects

    # Step 3: POST credentials (mimicking the SPA's form submission)
    r = session.post(
        login_url,
        data={
            "Email": email,
            "Password": password,
            "__RequestVerificationToken": csrf_token,
            "RememberMe": "false",
            "CountryCode": country,
        },
        allow_redirects=False,
        timeout=_TIMEOUT,
    )

    # Step 4: Follow the redirect chain until we find the auth code
    for _ in range(10):
        location = r.headers.get("Location", "")
        code_match = re.search(r"[?&]code=([0-9A-Za-z_-]+)", location)
        if code_match:
            return _exchange_code(code_match.group(1), verifier)
        if not location:
            break
        next_url = (
            location
            if location.startswith("http")
            else f"{_AUTH_API}{location}"
        )
        r = session.get(next_url, allow_redirects=False, timeout=_TIMEOUT)

    raise LidlAuthError(
        "Login failed — no auth code in redirect chain. "
        "Lidl may require CAPTCHA verification for this login."
    )


class LidlApiClient:
    """Minimal Lidl Plus API client using a refresh token."""

    def __init__(self, language: str, country: str, refresh_token: str) -> None:
        self._language = language.lower()
        self._country = country.upper()
        self._refresh_token = refresh_token
        self._access_token = ""
        self._expires: datetime | None = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _default_headers(self) -> dict:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "App-Version": _APP_VERSION,
            "Operating-System": _OS,
            "App": _APP,
            "Accept-Language": f"{self._language}-{self._country}",
            "User-Agent": f"LidlPlus/{_APP_VERSION} (iPhone; {_OS} 17.0; Scale/3.00)",
        }

    def _ensure_token(self) -> None:
        if self._access_token and self._expires and datetime.utcnow() < self._expires:
            return
        self._renew()

    def _renew(self) -> None:
        secret = base64.b64encode(f"{_CLIENT_ID}:secret".encode()).decode()
        headers = {
            "Authorization": f"Basic {secret}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            resp = requests.post(
                f"{_AUTH_API}/connect/token",
                headers=headers,
                data=payload,
                timeout=_TIMEOUT,
            )
            data = resp.json()
        except Exception as exc:
            raise LidlAuthError(f"Token request failed: {exc}") from exc

        if "access_token" not in data:
            raise LidlAuthError(f"Token renewal failed: {data.get('error', data)}")

        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        self._expires = datetime.utcnow() + timedelta(seconds=data["expires_in"] - 60)

    @property
    def refresh_token(self) -> str:
        """Return current refresh token (may have been rotated)."""
        return self._refresh_token

    def validate(self) -> bool:
        """Try to get a token; return True on success."""
        try:
            self._renew()
            return True
        except LidlAuthError:
            return False

    # ------------------------------------------------------------------
    # Coupons
    # ------------------------------------------------------------------

    def coupons(self) -> list[dict]:
        """Return flat list of all promotions."""
        headers = {**self._default_headers(), "Country": self._country}
        resp = requests.get(
            f"{_COUPONS_API}/v2/promotionsList",
            headers=headers,
            timeout=_TIMEOUT,
        )
        data = resp.json()
        promotions = []
        for section in data.get("sections", []):
            promotions.extend(section.get("promotions", []))
        return promotions

    def activate_coupon(self, coupon_id: str) -> bool:
        """Activate a single coupon. Returns True on success."""
        headers = {**self._default_headers(), "Country": self._country}
        resp = requests.post(
            f"{_COUPONS_API}/v1/promotions/{coupon_id}/activation",
            headers=headers,
            timeout=_TIMEOUT,
        )
        return resp.status_code in (200, 201, 204)

    def activate_all_coupons(self) -> dict:
        """Activate all available (not yet activated) coupons."""
        all_coupons = self.coupons()
        results = {"activated": 0, "skipped": 0, "failed": 0}
        for coupon in all_coupons:
            if coupon.get("isActivated"):
                results["skipped"] += 1
                continue
            ok = self.activate_coupon(coupon["id"])
            if ok:
                results["activated"] += 1
            else:
                results["failed"] += 1
        return results

    # ------------------------------------------------------------------
    # Receipts / Tickets
    # ------------------------------------------------------------------

    def tickets(self, page: int = 1, only_favorite: bool = False) -> dict:
        """Fetch one page of receipts."""
        url = (
            f"{_TICKET_API}/{self._country}/tickets"
            f"?pageNumber={page}&onlyFavorite={only_favorite}"
        )
        resp = requests.get(url, headers=self._default_headers(), timeout=_TIMEOUT)
        return resp.json()

    def recent_tickets(self, count: int = 10) -> list[dict]:
        """Return up to `count` most recent receipts."""
        data = self.tickets(page=1)
        return data.get("tickets", [])[:count]
