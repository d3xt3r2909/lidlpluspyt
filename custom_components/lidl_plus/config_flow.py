"""Config flow for Lidl Plus integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ACTIVATION_DAY,
    CONF_ACTIVATION_HOUR,
    CONF_COUNTRY,
    CONF_LANGUAGE,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ACTIVATION_DAY,
    DEFAULT_ACTIVATION_HOUR,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    WEEKDAYS,
)
from .lidl_api import LidlApiClient, LidlAuthError


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
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LANGUAGE, default="de"): str,
                    vol.Required(CONF_COUNTRY, default="DE"): str,
                    vol.Required(CONF_REFRESH_TOKEN): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "how_to": (
                    "Run ./lidl-plus.sh auth --debug on your Mac to get a token."
                )
            },
        )

    # ------------------------------------------------------------------
    # Reauth: triggered by HA when token renewal fails
    # ------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: dict) -> FlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if user_input is not None:
            new_token = user_input.get(CONF_REFRESH_TOKEN, "").strip()
            client = LidlApiClient(
                language=entry.data[CONF_LANGUAGE],
                country=entry.data[CONF_COUNTRY],
                refresh_token=new_token,
            )
            try:
                valid = await self.hass.async_add_executor_job(client.validate)
                if valid:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_REFRESH_TOKEN: client.refresh_token},
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                errors["base"] = "invalid_auth"
            except LidlAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_REFRESH_TOKEN): str}),
            errors=errors,
            description_placeholders={
                "how_to": "Run ./lidl-plus.sh auth --debug on your Mac to get a new token."
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LidlPlusOptionsFlow:
        return LidlPlusOptionsFlow(config_entry)


class LidlPlusOptionsFlow(config_entries.OptionsFlow):
    """Handle Lidl Plus options (interval, etc.)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]
            coordinator.update_interval = __import__("datetime").timedelta(
                hours=user_input[CONF_UPDATE_INTERVAL]
            )
            coordinator.reschedule_activation(
                day=user_input[CONF_ACTIVATION_DAY],
                hour=user_input[CONF_ACTIVATION_HOUR],
            )
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=opts.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_HOURS),
                    ): vol.All(int, vol.Range(min=1, max=168)),
                    vol.Required(
                        CONF_ACTIVATION_DAY,
                        default=opts.get(CONF_ACTIVATION_DAY, DEFAULT_ACTIVATION_DAY),
                    ): vol.In({k: v for k, v in WEEKDAYS.items()}),
                    vol.Required(
                        CONF_ACTIVATION_HOUR,
                        default=opts.get(CONF_ACTIVATION_HOUR, DEFAULT_ACTIVATION_HOUR),
                    ): vol.All(int, vol.Range(min=0, max=23)),
                }
            ),
            description_placeholders={
                "days": ", ".join(f"{k}={v}" for k, v in WEEKDAYS.items())
            },
        )
