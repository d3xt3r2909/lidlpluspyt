"""Lidl Plus Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_COUNTRY, CONF_LANGUAGE, CONF_REFRESH_TOKEN, DOMAIN
from .coordinator import LidlPlusCoordinator
from .lidl_api import LidlApiClient, LidlAuthError, normalize_refresh_token

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


def _register_set_refresh_token_service(hass: HomeAssistant) -> None:
    """Works even when token validation fails (runs before validate in async_setup_entry)."""
    if hass.services.has_service(DOMAIN, "set_refresh_token"):
        return

    async def handle_set_refresh_token(call: ServiceCall) -> None:
        raw = call.data.get("refresh_token", "")
        new_token = normalize_refresh_token(raw)
        if not new_token:
            _LOGGER.error("lidl_plus.set_refresh_token: empty token after normalization")
            return

        entries = hass.config_entries.async_entries(DOMAIN)
        entry_id = call.data.get("config_entry_id")
        if entry_id:
            entry = hass.config_entries.async_get_entry(entry_id)
        elif len(entries) == 1:
            entry = entries[0]
        else:
            _LOGGER.error(
                "lidl_plus.set_refresh_token: specify config_entry_id (found %d entries)",
                len(entries),
            )
            return

        if entry is None:
            _LOGGER.error("lidl_plus.set_refresh_token: config entry not found")
            return

        client = LidlApiClient(
            language=entry.data[CONF_LANGUAGE],
            country=entry.data[CONF_COUNTRY],
            refresh_token=new_token,
        )
        try:
            valid = await hass.async_add_executor_job(client.validate)
        except LidlAuthError as exc:
            _LOGGER.error("lidl_plus.set_refresh_token: %s", exc)
            hass.components.persistent_notification.async_create(
                str(exc),
                title="Lidl Plus — token rejected",
                notification_id="lidl_plus_token_invalid",
            )
            return
        if not valid:
            _LOGGER.error("lidl_plus.set_refresh_token: Lidl rejected the token")
            hass.components.persistent_notification.async_create(
                "Lidl rejected the refresh token. Paste only the token line (no dashes). "
                "Country + language in HA must match your auth CLI (e.g. DE + de). "
                "Regenerate with `./lidl-auth.sh --debug`.",
                title="Lidl Plus — invalid token",
                notification_id="lidl_plus_token_invalid",
            )
            return

        rotated = client.refresh_token
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_REFRESH_TOKEN: rotated}
        )
        _LOGGER.info("Lidl Plus refresh token updated and validated")
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, "set_refresh_token", handle_set_refresh_token)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Lidl Plus from a config entry."""
    _register_set_refresh_token_service(hass)

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

    async def handle_activate_all_coupons(call: ServiceCall) -> None:
        results = await hass.async_add_executor_job(client.activate_all_coupons)
        _LOGGER.info("Lidl Plus coupons activated: %s", results)
        await coordinator.async_request_refresh()
        hass.components.persistent_notification.async_create(
            f"✅ Activated: {results.get('activated', 0)} "
            f"· Skipped: {results.get('skipped', 0)} "
            f"· Failed: {results.get('failed', 0)}",
            title="Lidl Plus Coupons",
            notification_id="lidl_plus_activation",
        )

    hass.services.async_register(DOMAIN, "activate_all_coupons", handle_activate_all_coupons)

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
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unloaded
