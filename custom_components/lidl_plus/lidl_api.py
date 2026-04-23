"""Lidl Plus API client — no browser dependency, refresh-token based."""
from __future__ import annotations

import base64
import logging
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
_APP = "com.lidl.eci.lidl.plus"          # used in API request headers
_REDIRECT_URI = "com.lidlplus.app"        # original OAuth redirect scheme
_OS = "iOS"
_APP_VERSION = "13.0.0"
_TIMEOUT = 30

_LOGGER = logging.getLogger(__name__)


class LidlAuthError(Exception):
    """Raised when authentication fails (expired/invalid refresh token)."""


def normalize_refresh_token(value: str) -> str:
    """Strip whitespace, newlines, optional Bearer prefix / quotes from pasted tokens."""
    s = (value or "").strip()
    s = "".join(s.split())  # remove internal newlines / spaces
    low = s.lower()
    if low.startswith("bearer "):
        s = s[7:].strip()
        s = "".join(s.split())
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1].strip()
        s = "".join(s.split())
    return s


# ---------------------------------------------------------------------------
# Standalone headless login (no browser needed)
# ---------------------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(language: str, country: str) -> tuple[str, str]:
    """
    Generate a Lidl PKCE auth URL to open in any browser.

    Returns (url, verifier). Keep the verifier — you need it to exchange the
    code that comes back in the callback URL.
    """
    language = language.lower()
    country = country.upper()
    verifier, challenge = _pkce_pair()
    params = (
        f"client_id={_CLIENT_ID}"
        f"&response_type=code"
        f"&scope=openid%20profile%20offline_access%20lpprofile%20lpapis"
        f"&redirect_uri={_REDIRECT_URI}%3A%2F%2Fcallback"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
        f"&Country={country}"
        f"&language={language}-{country}"
    )
    url = f"{_AUTH_API}/connect/authorize?{params}"
    return url, verifier


def exchange_callback_url(callback_url_or_code: str, verifier: str) -> str:
    """
    Given the callback URL (or just the code string) pasted by the user,
    extract the auth code and exchange it for a refresh token.
    """
    code_match = re.search(r"[?&]code=([0-9A-Za-z_-]+)", callback_url_or_code)
    if not code_match:
        # Maybe the user pasted just the code itself
        if re.fullmatch(r"[0-9A-Za-z_-]{20,}", callback_url_or_code.strip()):
            code = callback_url_or_code.strip()
        else:
            raise LidlAuthError(
                "Could not find an auth code in the pasted URL. "
                "Make sure you copied the full address bar URL after logging in."
            )
    else:
        code = code_match.group(1)
    return _exchange_code(code, verifier)


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
            "redirect_uri": f"{_REDIRECT_URI}://callback",
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
        "redirect_uri": f"{_REDIRECT_URI}://callback",
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
        self._refresh_token = normalize_refresh_token(refresh_token)
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
        except Exception as exc:
            raise LidlAuthError(f"Token request failed: {exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise LidlAuthError(
                f"Token renewal: expected JSON, got HTTP {resp.status_code}: {resp.text[:200]!r}"
            ) from exc

        if "access_token" not in data:
            err = data.get("error_description") or data.get("error") or data
            _LOGGER.warning("Lidl /connect/token failed: %s", err)
            raise LidlAuthError(f"Token renewal failed: {err}")

        self._access_token = data["access_token"]
        # Lidl usually rotates refresh_token + expires_in; if omitted, keep prior token / sane TTL.
        new_rt = data.get("refresh_token")
        if isinstance(new_rt, str) and new_rt.strip():
            self._refresh_token = new_rt.strip()
        try:
            expires_in = int(data.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        ttl = max(120, expires_in - 60)
        self._expires = datetime.utcnow() + timedelta(seconds=ttl)

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
        except Exception as exc:  # noqa: BLE001
            # Avoid bubbling KeyError/TypeError from odd token payloads as "cannot connect" in config flow.
            _LOGGER.warning("Lidl token validate failed: %s", exc)
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
