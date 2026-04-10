"""DataUpdateCoordinator for Lidl Plus."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_REFRESH_TOKEN, DOMAIN, UPDATE_INTERVAL_HOURS
from .lidl_api import LidlApiClient, LidlAuthError

_LOGGER = logging.getLogger(__name__)


class LidlPlusCoordinator(DataUpdateCoordinator):
    """Fetches coupons and receipts from Lidl Plus API."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: LidlApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict:
        try:
            coupons = await self.hass.async_add_executor_job(self.client.coupons)
            tickets = await self.hass.async_add_executor_job(self.client.recent_tickets, 25)

            # Persist rotated refresh token back to config entry
            new_token = self.client.refresh_token
            if new_token != self.entry.data.get(CONF_REFRESH_TOKEN):
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_REFRESH_TOKEN: new_token},
                )

            return {
                "coupons": coupons,
                "tickets": tickets,
                "updated_at": datetime.utcnow().isoformat(),
            }
        except LidlAuthError as exc:
            raise UpdateFailed(f"Lidl Plus authentication failed: {exc}") from exc
        except Exception as exc:
            raise UpdateFailed(f"Lidl Plus update failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Derived helpers used by sensors
    # ------------------------------------------------------------------

    @property
    def coupons_available(self) -> int:
        if not self.data:
            return 0
        return sum(1 for c in self.data["coupons"] if not c.get("isActivated"))

    @property
    def coupons_activated(self) -> int:
        if not self.data:
            return 0
        return sum(1 for c in self.data["coupons"] if c.get("isActivated"))

    @property
    def last_receipt(self) -> dict | None:
        if not self.data or not self.data["tickets"]:
            return None
        return self.data["tickets"][0]

    @property
    def last_receipt_amount(self) -> float | None:
        receipt = self.last_receipt
        if not receipt:
            return None
        raw = receipt.get("totalAmount") or receipt.get("total", {}).get("amount")
        try:
            return float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            return None

    @property
    def last_receipt_date(self) -> str | None:
        receipt = self.last_receipt
        if not receipt:
            return None
        return receipt.get("date") or receipt.get("dateTime")

    @property
    def monthly_spending(self) -> float:
        if not self.data:
            return 0.0
        now = datetime.utcnow()
        total = 0.0
        for ticket in self.data["tickets"]:
            raw_date = ticket.get("date") or ticket.get("dateTime", "")
            try:
                date = datetime.fromisoformat(raw_date[:10])
                if date.year == now.year and date.month == now.month:
                    raw = ticket.get("totalAmount") or ticket.get("total", {}).get("amount", 0)
                    total += float(str(raw).replace(",", "."))
            except (ValueError, TypeError):
                continue
        return round(total, 2)
