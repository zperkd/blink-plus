"""Polling leaves the Sync Module alone: load reductions on, no poll during live view."""

from pytest_homeassistant.common import MockConfigEntry
from test_integration import (
    account as account,
)
from test_integration import (
    blink as blink,
)
from test_integration import (
    custom_integrations as custom_integrations,
)

DOMAIN = "blink_plus"


async def started(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_usb_clip_list_is_off_by_default(hass, account, blink):
    coordinator = await started(hass, account)
    assert blink.blink_plus_usb_clip_minutes == 0
    assert set(coordinator.load_reductions) == {
        "prepare_download",
        "local_storage_manifest",
        "network_info",
        "sensor_info",
    }
    await hass.config_entries.async_unload(account.entry_id)


async def test_usb_clip_minutes_option_reaches_blinkpy(hass, blink):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="test@example.com",
        unique_id="test@example.com",
        data={"username": "test@example.com", "token": "not-real"},
        options={"usb_clip_minutes": 2, "scan_interval": 30},
    )
    entry.add_to_hass(hass)
    coordinator = await started(hass, entry)
    assert blink.blink_plus_usb_clip_minutes == 2
    assert coordinator.update_interval.total_seconds() == 30
    await hass.config_entries.async_unload(entry.entry_id)


async def test_no_poll_while_a_live_view_runs(hass, account, blink):
    coordinator = await started(hass, account)
    blink.refresh.reset_mock()
    blink.clip_list.reset_mock()

    relay = coordinator.relay(blink.cameras["Test camera"])
    relay.runner = object()  # a live view is starting or running
    await coordinator.async_refresh()
    blink.refresh.assert_not_awaited()
    blink.clip_list.assert_not_awaited()
    assert coordinator.last_update_success

    relay.runner = None
    await coordinator.async_refresh()
    blink.refresh.assert_awaited_once()
    await hass.config_entries.async_unload(account.entry_id)


async def test_options_accept_usb_clip_minutes_and_30_s_polling(hass, account, blink):
    await started(hass, account)
    result = await hass.config_entries.options.async_init(account.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"scan_interval": 30, "usb_clip_minutes": 2},
    )
    assert account.options["usb_clip_minutes"] == 2
    assert account.options["scan_interval"] == 30
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(account.entry_id)


async def test_diagnostics_show_the_load_reductions(hass, account, blink):
    from custom_components.blink_plus.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    await started(hass, account)
    data = await async_get_config_entry_diagnostics(hass, account)
    assert data["usb_clip_minutes"] == 0
    assert set(data["blinkpy_load_reductions"]) >= {"local_storage_manifest"}
    await hass.config_entries.async_unload(account.entry_id)
