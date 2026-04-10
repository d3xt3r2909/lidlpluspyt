"""Lidl Plus Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_COUNTRY, CONF_LANGUAGE, CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import LidlPlusCoordinator
from .lidl_api import LidlApiClient, LidlAuthError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lidl Plus from a config entry."""
    client = LidlApiClient(
        language=entry.data[CONF_LANGUAGE],
        country=entry.data[CONF_COUNTRY],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
    )

    try:
        valid = await hass.async_add_executor_job(client.validate)
        if not valid:
            entry.async_start_reauth(hass)
            raise ConfigEntryNotReady("Lidl Plus token is invalid — re-authentication required.")
    except LidlAuthError as exc:
        entry.async_start_reauth(hass)
        raise ConfigEntryNotReady(str(exc)) from exc

    coordinator = LidlPlusCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register service: lidl_plus.activate_all_coupons
    async def handle_activate_all_coupons(call: ServiceCall) -> None:
        results = await hass.async_add_executor_job(client.activate_all_coupons)
        _LOGGER.info("Lidl Plus coupons activated: %s", results)
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "activate_all_coupons", handle_activate_all_coupons)

    # Register service: lidl_plus.set_refresh_token
    async def handle_set_refresh_token(call: ServiceCall) -> None:
        new_token = call.data.get("refresh_token", "").strip()
        if not new_token:
            _LOGGER.error("lidl_plus.set_refresh_token: no token provided")
            return
        client._refresh_token = new_token
        client._access_token = ""  # force re-auth on next API call
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_REFRESH_TOKEN: new_token}
        )
        _LOGGER.info("Lidl Plus refresh token updated via service call")
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "set_refresh_token", handle_set_refresh_token)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator and coordinator._unsub_activation:
        coordinator._unsub_activation()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.services.async_remove(DOMAIN, "activate_all_coupons")
        hass.services.async_remove(DOMAIN, "set_refresh_token")
    return unloaded
