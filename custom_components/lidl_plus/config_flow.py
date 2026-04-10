"""Config flow for Lidl Plus integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ACTIVATION_DAY,
    CONF_ACTIVATION_HOUR,
    CONF_COUNTRY,
    CONF_EMAIL,
    CONF_LANGUAGE,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ACTIVATION_DAY,
    DEFAULT_ACTIVATION_HOUR,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    WEEKDAYS,
)
from .lidl_api import LidlApiClient, LidlAuthError, login_with_credentials


class LidlPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lidl Plus."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """First step: choose setup method."""
        if user_input is not None:
            self._step_user_data = user_input
            if user_input.get("method") == "credentials":
                return await self.async_step_credentials()
            return await self.async_step_token()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("method", default="credentials"): vol.In(
                        {
                            "credentials": "Email & password (recommended)",
                            "token": "Paste refresh token manually",
                        }
                    ),
                    vol.Required(CONF_LANGUAGE, default="de"): str,
                    vol.Required(CONF_COUNTRY, default="DE"): str,
                }
            ),
        )

    # ------------------------------------------------------------------
    # Path A: email + password → headless login
    # ------------------------------------------------------------------

    async def async_step_credentials(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        # Pull language/country carried from step_user
        stored = getattr(self, "_step_user_data", {})

        if user_input is not None:
            language = stored.get(CONF_LANGUAGE, "de")
            country = stored.get(CONF_COUNTRY, "DE")
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            try:
                refresh_token = await self.hass.async_add_executor_job(
                    login_with_credentials, language, country, email, password
                )
                data = {
                    CONF_LANGUAGE: language,
                    CONF_COUNTRY: country,
                    CONF_REFRESH_TOKEN: refresh_token,
                    CONF_EMAIL: email,
                    CONF_PASSWORD: password,
                }
                unique_id = f"{country}_{language}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Lidl Plus ({country})",
                    data=data,
                )
            except LidlAuthError as exc:
                if "CAPTCHA" in str(exc):
                    errors["base"] = "captcha_required"
                else:
                    errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "note": (
                    "If login fails with 'captcha_required', use the "
                    "'Paste refresh token' method instead."
                )
            },
        )

    # ------------------------------------------------------------------
    # Path B: paste token manually
    # ------------------------------------------------------------------

    async def async_step_token(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        stored = getattr(self, "_step_user_data", {})

        if user_input is not None:
            language = stored.get(CONF_LANGUAGE, "de")
            country = stored.get(CONF_COUNTRY, "DE")
            client = LidlApiClient(
                language=language,
                country=country,
                refresh_token=user_input[CONF_REFRESH_TOKEN],
            )
            try:
                valid = await self.hass.async_add_executor_job(client.validate)
                if not valid:
                    errors["base"] = "invalid_auth"
                else:
                    data = {
                        CONF_LANGUAGE: language,
                        CONF_COUNTRY: country,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                    }
                    unique_id = f"{country}_{language}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Lidl Plus ({country})",
                        data=data,
                    )
            except LidlAuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required(CONF_REFRESH_TOKEN): str}),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Reauth: shown by HA when the token renewal fails
    # ------------------------------------------------------------------

    async def async_step_reauth(self, entry_data: dict) -> FlowResult:
        """Start reauth when HA detects the token is invalid."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        has_credentials = bool(
            entry.data.get(CONF_EMAIL) and entry.data.get(CONF_PASSWORD)
        )

        if user_input is not None:
            language = entry.data[CONF_LANGUAGE]
            country = entry.data[CONF_COUNTRY]
            new_token: str | None = None

            # Try credential-based renewal first (if credentials available)
            if has_credentials and not user_input.get(CONF_REFRESH_TOKEN):
                try:
                    new_token = await self.hass.async_add_executor_job(
                        login_with_credentials,
                        language,
                        country,
                        entry.data[CONF_EMAIL],
                        entry.data[CONF_PASSWORD],
                    )
                except LidlAuthError:
                    errors["base"] = "captcha_required"

            # Fall back to / use manual token
            if not new_token and user_input.get(CONF_REFRESH_TOKEN):
                client = LidlApiClient(
                    language=language,
                    country=country,
                    refresh_token=user_input[CONF_REFRESH_TOKEN],
                )
                try:
                    valid = await self.hass.async_add_executor_job(client.validate)
                    if valid:
                        new_token = client.refresh_token
                    else:
                        errors["base"] = "invalid_auth"
                except LidlAuthError:
                    errors["base"] = "invalid_auth"
                except Exception:  # noqa: BLE001
                    errors["base"] = "cannot_connect"

            if new_token:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_REFRESH_TOKEN: new_token},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Optional(CONF_REFRESH_TOKEN): str}
            ),
            errors=errors,
            description_placeholders={
                "method": (
                    "Leave the token field empty to retry with your saved credentials."
                    if has_credentials
                    else "Enter a new refresh token obtained from the lidl-auth script."
                )
            },
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
