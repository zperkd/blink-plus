from test_integration import (
    account as account,
    blink as blink,
    custom_integrations as custom_integrations,
)

"""Expanded real-HA tests for errors, reauth, capabilities and unload."""

from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from blinkpy.auth import UnauthorizedError


async def test_command_cloud_refresh_error_is_safe(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    coordinator = account.runtime_data
    blink.refresh.side_effect = UnauthorizedError("sensitive upstream exception")
    with pytest.raises(HomeAssistantError):
        await coordinator.command(AsyncMock(return_value=True))
    await hass.config_entries.async_unload(account.entry_id)


async def test_command_rejected_response(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    with pytest.raises(HomeAssistantError):
        await account.runtime_data.command(
            AsyncMock(return_value=SimpleNamespace(status=403))
        )
    await hass.config_entries.async_unload(account.entry_id)


async def test_options_available_when_account_unloaded(hass, account, blink):
    result = await hass.config_entries.options.async_init(account.entry_id)
    assert result["type"] is FlowResultType.FORM


async def test_existing_reauth_identity_preserved(hass, account, blink):
    hass.config_entries.async_update_entry(
        account, data={**account.data, "hardware_id": "stable-test-device"}
    )
    auth = MagicMock(
        login_attributes={"username": "test@example.com", "token": "updated"}
    )
    with patch(
        "custom_components.blink_plus.config_flow.Auth", return_value=auth
    ) as constructor:
        result = await hass.config_entries.flow.async_init(
            "blink_plus",
            context={"source": "reauth", "entry_id": account.entry_id},
            data=account.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"username": "test@example.com", "password": "private"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert constructor.call_args.args[0]["hardware_id"] == "stable-test-device"
    assert "password" not in account.data
    await hass.async_block_till_done()


async def test_reauth_rejects_other_account(hass, account, blink):
    result = await hass.config_entries.flow.async_init(
        "blink_plus",
        context={"source": "reauth", "entry_id": account.entry_id},
        data=account.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"username": "other@example.com", "password": "private"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    blink.start.assert_not_awaited()


async def test_late_reading_adds_sensor(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    camera = blink.cameras["Test camera"]
    camera.temperature_calibrated = 70
    account.runtime_data.async_set_updated_data({"TEST123": {"temperature": 70}})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.test_camera_temperature")
    assert state.attributes["unit_of_measurement"] == "°C"
    assert float(state.state) == pytest.approx((70 - 32) * 5 / 9)
    await hass.config_entries.async_unload(account.entry_id)


async def test_live_disabled_never_allocates_relay(hass, account, blink):
    hass.config_entries.async_update_entry(account, options={"live_enabled": False})
    await hass.config_entries.async_setup(account.entry_id)
    from homeassistant.components.camera import get_camera_from_entity_id

    camera = get_camera_from_entity_id(hass, "camera.test_camera")
    assert await camera.stream_source() is None
    assert not account.runtime_data.relays
    await hass.config_entries.async_unload(account.entry_id)


async def test_diagnostics_no_identifiers_or_auth(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    from custom_components.blink_plus.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    import json

    result = json.dumps(await async_get_config_entry_diagnostics(hass, account))
    for secret in ("TEST123", "test@example.com", "not-real", "Test camera"):
        assert secret not in result
    await hass.config_entries.async_unload(account.entry_id)


async def test_stream_creation_keeps_audio_probe_and_does_not_wake(
    hass, account, blink, socket_enabled
):
    await hass.config_entries.async_setup(account.entry_id)
    from homeassistant.components.camera import get_camera_from_entity_id

    camera = get_camera_from_entity_id(hass, "camera.test_camera")
    stream = await camera.async_create_stream()
    assert "analyzeduration" not in stream.pyav_options
    assert "probesize" not in stream.pyav_options
    blink.cameras["Test camera"].init_livestream.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_invalid_options_are_rejected(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    result = await hass.config_entries.options.async_init(account.entry_id)
    from homeassistant.data_entry_flow import InvalidData

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={"scan_interval": -1}
        )
    assert "scan_interval" not in account.options
    await hass.config_entries.async_unload(account.entry_id)


async def test_snapshot_waits_until_publication(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    camera = blink.cameras["Test camera"]
    camera.thumbnail = "old"

    async def refreshed(*args, **kwargs):
        camera.thumbnail = "new"

    blink.refresh.side_effect = refreshed
    with patch(
        "custom_components.blink_plus.coordinator.asyncio.sleep", new=AsyncMock()
    ):
        await account.runtime_data.snapshot(camera)
    assert camera.thumbnail == "new"
    camera.snap_picture.assert_awaited_once()
    await hass.config_entries.async_unload(account.entry_id)


async def test_snapshot_failure_is_reported(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    camera = blink.cameras["Test camera"]
    camera.thumbnail = "old"
    with patch(
        "custom_components.blink_plus.coordinator.asyncio.sleep", new=AsyncMock()
    ):
        with pytest.raises(HomeAssistantError, match="publish a fresh snapshot"):
            await account.runtime_data.snapshot(camera)
    await hass.config_entries.async_unload(account.entry_id)


async def test_local_recording_respects_disabled_live_view(hass, account, blink):
    hass.config_entries.async_update_entry(account, options={"live_enabled": False})
    await hass.config_entries.async_setup(account.entry_id)
    with pytest.raises(HomeAssistantError, match="Enable live video"):
        await account.runtime_data.record_local(blink.cameras["Test camera"])
    blink.cameras["Test camera"].init_livestream.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_local_recording_rejects_disallowed_directory(hass, account, blink):
    hass.config_entries.async_update_entry(
        account, options={"recording_directory": "/etc/blink-plus-not-allowed"}
    )
    await hass.config_entries.async_setup(account.entry_id)
    with pytest.raises(HomeAssistantError, match="allowed media directories"):
        await account.runtime_data.record_local(blink.cameras["Test camera"])
    blink.cameras["Test camera"].init_livestream.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_local_recording_rejects_duplicate(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    account.runtime_data.recording.add("TEST123")
    with pytest.raises(HomeAssistantError, match="already running"):
        await account.runtime_data.record_local(blink.cameras["Test camera"])
    await hass.config_entries.async_unload(account.entry_id)


async def test_local_recording_rejects_short_session(hass, account, blink, tmp_path):
    directory = str(tmp_path / "recordings")
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    hass.config_entries.async_update_entry(
        account,
        options={
            "recording_directory": directory,
            "recording_seconds": 30,
            "max_live_seconds": 15,
        },
    )
    await hass.config_entries.async_setup(account.entry_id)
    with pytest.raises(HomeAssistantError, match="live-session limit"):
        await account.runtime_data.record_local(blink.cameras["Test camera"])
    blink.cameras["Test camera"].init_livestream.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_preload_stream_is_forced_off(hass, account, blink, socket_enabled):
    await hass.config_entries.async_setup(account.entry_id)
    from homeassistant.components.camera import get_camera_from_entity_id
    from homeassistant.components.camera.const import DATA_CAMERA_PREFS

    await hass.data[DATA_CAMERA_PREFS].async_update(
        "camera.test_camera", preload_stream=True
    )
    camera = get_camera_from_entity_id(hass, "camera.test_camera")
    stream = await camera.async_create_stream()
    settings = stream.dynamic_stream_settings
    assert settings.preload_stream is False
    settings.preload_stream = True
    assert settings.preload_stream is False
    stored = await hass.data[DATA_CAMERA_PREFS].get_dynamic_stream_settings(
        "camera.test_camera"
    )
    assert stored.preload_stream is True
    assert settings.orientation == stored.orientation
    assert await camera.async_create_stream() is stream
    assert stream.dynamic_stream_settings is settings
    blink.cameras["Test camera"].init_livestream.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_camera_entity_registry_follows_lifecycle(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    coordinator = account.runtime_data
    assert coordinator.camera_entities["TEST123"].entity_id == "camera.test_camera"
    await hass.config_entries.async_unload(account.entry_id)
    assert not coordinator.camera_entities
