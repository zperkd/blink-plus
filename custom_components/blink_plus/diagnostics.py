"""Allowlisted diagnostics: no account identifiers, tokens, URLs or serials."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "version": "0.1.0",
        "camera_count": len(coordinator.api.cameras),
        "scan_interval": coordinator.options["scan_interval"],
        "live_enabled": coordinator.options["live_enabled"],
        "max_live_seconds": coordinator.options["max_live_seconds"],
        "active_streams": sum(
            r.stream is not None for r in coordinator.relays.values()
        ),
        "streams": [
            {"starts": r.starts, "last_error": r.last_error}
            for r in coordinator.relays.values()
        ],
    }
