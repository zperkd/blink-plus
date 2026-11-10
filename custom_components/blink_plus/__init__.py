"""Self-contained Blink cameras, controls and sensors."""

from homeassistant.helpers import config_validation as cv
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from .const import DEFAULTS, DOMAIN, PLATFORMS
from .coordinator import BlinkCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass, config):
    from .live_http import BlinkLiveView
    from .media_source import BlinkCloudView

    hass.http.register_view(BlinkCloudView())
    hass.http.register_view(BlinkLiveView())
    return True


async def async_setup_entry(hass, entry):
    coordinator = BlinkCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.close()
        raise

    async def shutdown(event):
        await coordinator.close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown)
    )
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass, entry):
    # Saved token refreshes also update the entry; only option changes need a reload.
    if {**DEFAULTS, **entry.options} != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.close()
        return True
    return False
