"""Config flow for Lidl Plus integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_COUNTRY,
    CONF_LANGUAGE,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)
from .lidl_api import LidlApiClient, LidlAuthError

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LANGUAGE, default="de"): str,
        vol.Required(CONF_COUNTRY, default="DE"): str,
        vol.Required(CONF_REFRESH_TOKEN): str,
    }
)


class LidlPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lidl Plus."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client = LidlApiClient(
                language=user_input[CONF_LANGUAGE],
                country=user_input[CONF_COUNTRY],
                refresh_token=user_input[CONF_REFRESH_TOKEN],
            )
            try:
                valid = await self.hass.async_add_executor_job(client.validate)
                if not valid:
                    errors["base"] = "invalid_auth"
                else:
                    user_input[CONF_REFRESH_TOKEN] = client.refresh_token
                    unique_id = f"{user_input[CONF_COUNTRY]}_{user_input[CONF_LANGUAGE]}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Lidl Plus ({user_input[CONF_COUNTRY]})",
                        data=user_input,
                    )
            except LidlAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> LidlPlusOptionsFlow:
        return LidlPlusOptionsFlow(config_entry)


class LidlPlusOptionsFlow(config_entries.OptionsFlow):
    """Handle Lidl Plus options (interval, etc.)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            # Reload coordinator with new interval
            self.hass.data[DOMAIN][self._config_entry.entry_id].update_interval = (
                __import__("datetime").timedelta(hours=user_input[CONF_UPDATE_INTERVAL])
            )
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_UPDATE_INTERVAL, default=current_interval): vol.All(
                        int, vol.Range(min=1, max=168)  # 1 hour to 1 week
                    ),
                }
            ),
        )
