"""Lidl Plus API client — no browser dependency, refresh-token based."""
from __future__ import annotations

import base64
import hashlib
import os
import re
from datetime import datetime, timedelta

import requests

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
