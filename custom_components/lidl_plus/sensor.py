"""Lidl Plus sensors."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LidlPlusCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LidlPlusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        LidlCouponsAvailableSensor(coordinator, entry),
        LidlCouponsActivatedSensor(coordinator, entry),
        LidlLastReceiptAmountSensor(coordinator, entry),
        LidlLastReceiptDateSensor(coordinator, entry),
        LidlMonthlySpendingSensor(coordinator, entry),
    ])


class LidlBaseSensor(CoordinatorEntity[LidlPlusCoordinator], SensorEntity):
    """Base class for Lidl Plus sensors."""

    def __init__(self, coordinator: LidlPlusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Lidl Plus",
            "manufacturer": "Lidl",
            "model": "Lidl Plus API",
        }


class LidlCouponsAvailableSensor(LidlBaseSensor):
    _attr_name = "Lidl Plus Coupons Available"
    _attr_unique_id_suffix = "coupons_available"
    _attr_icon = "mdi:ticket-percent"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_coupons_available"

    @property
    def native_value(self) -> int:
        return self.coordinator.coupons_available

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        coupons = []
        for c in self.coordinator.data["coupons"]:
            discount_obj = c.get("discount") or {}
            validity_obj = c.get("validity") or {}
            coupons.append({
                "id": c.get("id"),
                "title": c.get("title") or c.get("offerTitle", ""),
                "description": discount_obj.get("description", ""),
                "discount": discount_obj.get("title", ""),
                "image": (
                    c.get("imageUrl")
                    or c.get("image")
                    or (c.get("images") or [{}])[0].get("url", "")
                ),
                "valid_until": (validity_obj.get("end") or "")[:10],
                "activated": c.get("isActivated", False),
                "channel": c.get("channel", ""),
                "is_special": c.get("isSpecial", False),
            })
        return {
            "coupons": [c for c in coupons if not c["activated"]],
            "coupons_activated": [c for c in coupons if c["activated"]],
        }


class LidlCouponsActivatedSensor(LidlBaseSensor):
    _attr_name = "Lidl Plus Coupons Activated"
    _attr_icon = "mdi:ticket-confirmation"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_coupons_activated"

    @property
    def native_value(self) -> int:
        return self.coordinator.coupons_activated


class LidlLastReceiptAmountSensor(LidlBaseSensor):
    _attr_name = "Lidl Plus Last Receipt"
    _attr_icon = "mdi:receipt"
    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_last_receipt_amount"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.last_receipt_amount

    @property
    def extra_state_attributes(self) -> dict:
        receipt = self.coordinator.last_receipt
        if not receipt:
            return {}
        return {
            "date": self.coordinator.last_receipt_date,
            "store": receipt.get("store", {}).get("name") or receipt.get("storeName"),
            "items": receipt.get("itemsCount") or len(receipt.get("lineItems", [])),
        }


class LidlLastReceiptDateSensor(LidlBaseSensor):
    _attr_name = "Lidl Plus Last Receipt Date"
    _attr_icon = "mdi:calendar-check"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_last_receipt_date"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.last_receipt_date


class LidlMonthlySpendingSensor(LidlBaseSensor):
    _attr_name = "Lidl Plus Monthly Spending"
    _attr_icon = "mdi:cash-multiple"
    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_state_class = SensorStateClass.TOTAL

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_monthly_spending"

    @property
    def native_value(self) -> float:
        return self.coordinator.monthly_spending
