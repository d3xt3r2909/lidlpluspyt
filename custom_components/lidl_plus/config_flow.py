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
from .lidl_api import (
    LidlApiClient,
    LidlAuthError,
    build_auth_url,
    exchange_callback_url,
    login_with_credentials,
)

_CONF_CALLBACK_URL = "callback_url"


class LidlPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Lidl Plus."""

    VERSION = 1

    def __init__(self) -> None:
        self._language = "de"
        self._country = "DE"
        self._pkce_verifier: str = ""
        self._email: str = ""
        self._password: str = ""

    # ------------------------------------------------------------------
    # Step 1: method selection
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            self._language = user_input[CONF_LANGUAGE]
            self._country = user_input[CONF_COUNTRY]
            method = user_input.get("method", "browser")
            if method == "browser":
                return await self.async_step_browser_login()
            if method == "credentials":
                return await self.async_step_credentials()
            return await self.async_step_token()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("method", default="browser"): vol.In(
                        {
                            "browser": "Open browser to log in (any laptop/phone)",
                            "credentials": "Email & password (auto-renew, may fail on CAPTCHA)",
                            "token": "Paste refresh token manually",
                        }
                    ),
                    vol.Required(CONF_LANGUAGE, default="de"): str,
                    vol.Required(CONF_COUNTRY, default="DE"): str,
                }
            ),
        )

    # ------------------------------------------------------------------
    # Path A: browser login (open URL → paste callback)
    # ------------------------------------------------------------------

    async def async_step_browser_login(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        # Generate the auth URL the first time this step is shown
        if not self._pkce_verifier:
            auth_url, self._pkce_verifier = await self.hass.async_add_executor_job(
                build_auth_url, self._language, self._country
            )
            self._auth_url = auth_url

        if user_input is not None:
            pasted = user_input.get(_CONF_CALLBACK_URL, "").strip()
            try:
                refresh_token = await self.hass.async_add_executor_job(
                    exchange_callback_url, pasted, self._pkce_verifier
                )
                data = {
                    CONF_LANGUAGE: self._language,
                    CONF_COUNTRY: self._country,
                    CONF_REFRESH_TOKEN: refresh_token,
                }
                unique_id = f"{self._country}_{self._language}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Lidl Plus ({self._country})",
                    data=data,
                )
            except LidlAuthError:
                errors["base"] = "invalid_code"
                # Regenerate URL + verifier so a fresh attempt is possible
                auth_url, self._pkce_verifier = await self.hass.async_add_executor_job(
                    build_auth_url, self._language, self._country
                )
                self._auth_url = auth_url

        return self.async_show_form(
            step_id="browser_login",
            data_schema=vol.Schema({vol.Required(_CONF_CALLBACK_URL): str}),
            errors=errors,
            description_placeholders={"auth_url": self._auth_url},
        )

    # ------------------------------------------------------------------
    # Path B: email + password → headless login (no browser)
    # ------------------------------------------------------------------

    async def async_step_credentials(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            try:
                refresh_token = await self.hass.async_add_executor_job(
                    login_with_credentials,
                    self._language,
                    self._country,
                    self._email,
                    self._password,
                )
                data = {
                    CONF_LANGUAGE: self._language,
                    CONF_COUNTRY: self._country,
                    CONF_REFRESH_TOKEN: refresh_token,
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                }
                unique_id = f"{self._country}_{self._language}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Lidl Plus ({self._country})",
                    data=data,
                )
            except LidlAuthError as exc:
                errors["base"] = "captcha_required" if "CAPTCHA" in str(exc) else "invalid_auth"
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
        )

    # ------------------------------------------------------------------
    # Path C: paste token manually
    # ------------------------------------------------------------------

    async def async_step_token(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client = LidlApiClient(
                language=self._language,
                country=self._country,
                refresh_token=user_input[CONF_REFRESH_TOKEN],
            )
            try:
                valid = await self.hass.async_add_executor_job(client.validate)
                if not valid:
                    errors["base"] = "invalid_auth"
                else:
                    data = {
                        CONF_LANGUAGE: self._language,
                        CONF_COUNTRY: self._country,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                    }
                    unique_id = f"{self._country}_{self._language}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Lidl Plus ({self._country})",
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
        has_credentials = bool(
            entry.data.get(CONF_EMAIL) and entry.data.get(CONF_PASSWORD)
        )

        # Generate a fresh browser-login URL for the reauth form
        if not self._pkce_verifier:
            auth_url, self._pkce_verifier = await self.hass.async_add_executor_job(
                build_auth_url,
                entry.data[CONF_LANGUAGE],
                entry.data[CONF_COUNTRY],
            )
            self._auth_url = auth_url

        if user_input is not None:
            language = entry.data[CONF_LANGUAGE]
            country = entry.data[CONF_COUNTRY]
            new_token: str | None = None

            pasted = (user_input.get(_CONF_CALLBACK_URL) or "").strip()
            if pasted:
                # Browser-based reauth: user pasted callback URL
                try:
                    new_token = await self.hass.async_add_executor_job(
                        exchange_callback_url, pasted, self._pkce_verifier
                    )
                except LidlAuthError:
                    errors["base"] = "invalid_code"
                    # Fresh URL for retry
                    auth_url, self._pkce_verifier = await self.hass.async_add_executor_job(
                        build_auth_url, language, country
                    )
                    self._auth_url = auth_url

            elif has_credentials:
                # Try saved credentials silently
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

            if not errors and not new_token:
                errors["base"] = "invalid_auth"

            if new_token:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_REFRESH_TOKEN: new_token},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        description = (
            "Open the URL below in any browser, log in to Lidl Plus, "
            "then copy the full address bar URL after the redirect (it starts with "
            "com.lidlplus.app:// or shows an error page) and paste it below.\n\n"
            f"{self._auth_url}"
        )
        if has_credentials:
            description += (
                "\n\nAlternatively, leave the field empty to retry with your saved credentials."
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Optional(_CONF_CALLBACK_URL): str}),
            errors=errors,
            description_placeholders={"auth_url": self._auth_url, "note": description},
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
