"""UI setup, MFA, reauthentication and account options."""

import voluptuous as vol
from aiohttp import ClientError
from blinkpy.auth import Auth, BlinkTwoFARequiredError
from blinkpy.blinkpy import Blink
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from .const import DEFAULTS, DOMAIN
from .coordinator import AUTH_ERRORS, token_data


class BlinkPlusFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.blink = None
        self.reauth_entry = None
        self.username = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BlinkOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            self.username = user_input["username"].strip().lower()
            await self.async_set_unique_id(self.username)
            if self.reauth_entry is None:
                self._abort_if_unique_id_configured()
            elif self.username != self.reauth_entry.unique_id:
                return self.async_abort(reason="wrong_account")
            session = async_get_clientsession(self.hass)
            self.blink = Blink(session=session)
            login = {**user_input, "username": self.username}
            if self.reauth_entry and self.reauth_entry.data.get("hardware_id"):
                login["hardware_id"] = self.reauth_entry.data["hardware_id"]
            self.blink.auth = Auth(login, no_prompt=True, session=session)
            try:
                if await self.blink.start():
                    return self.finish()
                errors["base"] = "invalid_auth"
            except BlinkTwoFARequiredError:
                return await self.async_step_mfa()
            except AUTH_ERRORS:
                errors["base"] = "invalid_auth"
            except (ClientError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): str,
                    vol.Required("password"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_mfa(self, user_input=None):
        errors = {}
        if user_input:
            try:
                if await self.blink.send_2fa_code(user_input["pin"].strip()):
                    return self.finish()
                errors["base"] = "invalid_auth"
            except AUTH_ERRORS:
                errors["base"] = "invalid_auth"
            except (ClientError, OSError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({vol.Required("pin"): str}),
            errors=errors,
        )

    def finish(self):
        data = token_data(self.blink.auth)
        if self.reauth_entry:
            return self.async_update_reload_and_abort(
                self.reauth_entry, data_updates=data
            )
        return self.async_create_entry(title=self.username, data=data)

    async def async_step_reauth(self, entry_data):
        self.reauth_entry = self._get_reauth_entry()
        return await self.async_step_user()


class BlinkOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None):
        values = {**DEFAULTS, **self.config_entry.options}
        coordinator = getattr(self.config_entry, "runtime_data", None)
        cameras = coordinator.api.cameras.values() if coordinator else []
        choices = [{"value": str(c.serial), "label": c.name} for c in cameras]
        available = {item["value"] for item in choices}
        choices.extend(
            {"value": serial, "label": serial}
            for serial in values["pan_tilt_cameras"]
            if serial not in available
        )
        schema = {}
        for key, minimum, maximum in (
            ("scan_interval", 60, 3600),
            ("cloud_history_days", 1, 90),
            ("cloud_max_clips", 50, 5000),
            ("cloud_refresh_seconds", 15, 600),
            ("cloud_cache_mb", 16, 1024),
            ("recording_seconds", 15, 60),
            ("max_live_seconds", 15, 300),
            ("reconnect_cooldown", 5, 300),
            ("pan_step", 1, 45),
            ("tilt_step", 1, 30),
        ):
            schema[vol.Required(key, default=values[key])] = vol.All(
                vol.Coerce(int), vol.Range(min=minimum, max=maximum)
            )
        for key in ("live_enabled", "cloud_enabled", "invert_pan", "invert_tilt"):
            schema[vol.Required(key, default=values[key])] = bool
        schema[vol.Optional("pan_tilt_cameras", default=values["pan_tilt_cameras"])] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=choices,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        )
        schema[
            vol.Optional("recording_directory", default=values["recording_directory"])
        ] = str
        errors = {}
        if user_input is not None:
            try:
                validated = vol.Schema(schema)(
                    {key: user_input.get(key, values[key]) for key in DEFAULTS}
                )
            except vol.Invalid:
                errors["base"] = "invalid_options"
            else:
                return self.async_create_entry(title="", data={**values, **validated})
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors
        )
