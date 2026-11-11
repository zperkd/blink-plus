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


def overview(thumbnail):
    return {
        "networks": [{"id": 1, "name": "Home"}],
        "cameras": [{"id": 77, "name": "Other", "thumbnail": "/other"}],
        "owls": [{"id": 42, "name": "Test camera", "thumbnail": thumbnail}],
    }


async def test_snapshot_uses_the_light_overview_and_refreshes_once(
    hass, account, blink
):
    await hass.config_entries.async_setup(account.entry_id)
    camera = blink.cameras["Test camera"]
    camera.camera_id = 42
    camera.thumbnail = "old"
    camera.snap_picture = AsyncMock(return_value={"id": 5, "network_id": 1})
    answers = [overview("/t?ts=1"), overview("/t?ts=1"), overview("/t?ts=2")]

    async def homescreen():
        blink.homescreen = answers.pop(0)

    blink.get_homescreen.side_effect = homescreen
    blink.refresh.reset_mock()
    with patch(
        "custom_components.blink_plus.coordinator.asyncio.sleep", new=AsyncMock()
    ):
        await account.runtime_data.snapshot(camera)
    camera.snap_picture.assert_awaited_once()
    assert not answers
    # One full refresh to load the new picture, plus the one every command ends with.
    assert blink.refresh.await_count == 2
    await hass.config_entries.async_unload(account.entry_id)


async def test_snapshot_retries_while_blink_is_busy(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    camera = blink.cameras["Test camera"]
    camera.camera_id = 42
    camera.snap_picture = AsyncMock(
        side_effect=[
            {"message": "System is busy, please wait", "code": 307},
            {"id": 5, "network_id": 1},
        ]
    )
    answers = [overview("/t?ts=1"), overview("/t?ts=2")]

    async def homescreen():
        blink.homescreen = answers.pop(0)

    blink.get_homescreen.side_effect = homescreen
    with patch(
        "custom_components.blink_plus.coordinator.asyncio.sleep", new=AsyncMock()
    ):
        await account.runtime_data.snapshot(camera)
    assert camera.snap_picture.await_count == 2
    await hass.config_entries.async_unload(account.entry_id)


async def test_snapshot_reports_a_busy_blink(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    camera = blink.cameras["Test camera"]
    camera.snap_picture = AsyncMock(
        return_value={"message": "System is busy, please wait", "code": 307}
    )
    with patch(
        "custom_components.blink_plus.coordinator.asyncio.sleep", new=AsyncMock()
    ):
        with pytest.raises(HomeAssistantError, match="Blink is busy"):
            await account.runtime_data.snapshot(camera)
    assert camera.snap_picture.await_count == 3
    await hass.config_entries.async_unload(account.entry_id)


def test_overview_lookup_needs_matching_id_and_name():
    from custom_components.blink_plus.coordinator import blink_busy, listed_thumbnail

    camera = SimpleNamespace(camera_id=42, name="Test camera")
    assert listed_thumbnail(overview("/x"), camera) == "/x"
    assert (
        listed_thumbnail(overview("/x"), SimpleNamespace(camera_id=42, name="Renamed"))
        is None
    )
    assert listed_thumbnail(overview("/x"), SimpleNamespace(name="Test camera")) is None
    assert listed_thumbnail(None, camera) is None
    assert blink_busy({"message": "System is busy, please wait", "code": 307})
    assert not blink_busy({"id": 5, "message": "busy"})
    assert not blink_busy(True)


class DirectStream:
    """A fake blinkpy live stream that sends MPEG-TS packets to the relay's clients."""

    target_reader = None
    target_writer = None

    def __init__(self):
        self.clients = []

    async def recv(self):
        pass

    async def feed(self):
        import asyncio

        while True:
            for writer in tuple(self.clients):
                writer.write(b"\x47" + b"x" * 187)
                await writer.drain()
            await asyncio.sleep(0.01)

    def stop(self):
        for writer in tuple(self.clients):
            writer.close()


async def test_direct_live_stream_serves_the_relay(
    hass, account, blink, hass_client, socket_enabled, monkeypatch
):
    monkeypatch.setattr(
        "custom_components.blink_plus.transport.init_livestream",
        lambda camera: camera.init_livestream(),
    )
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    camera = blink.cameras["Test camera"]
    camera.init_livestream = AsyncMock(return_value=DirectStream())
    client = await hass_client()
    response = await client.get("/api/blink_plus/live/camera.test_camera")
    assert response.status == 200
    assert response.headers["Content-Type"] == "video/mp2t"
    data = await response.content.readexactly(188 * 3)
    assert data[0] == 0x47 and data[188] == 0x47
    relay = account.runtime_data.relays["TEST123"]
    assert relay.starts == 1
    response.close()
    for _ in range(100):
        if relay.runner is None:
            break
        import asyncio

        await asyncio.sleep(0.02)
    assert relay.runner is None  # The viewer left: the camera session ended.
    await hass.config_entries.async_unload(account.entry_id)


async def test_direct_live_stream_refuses_unknown_and_disabled(
    hass, account, blink, hass_client, hass_client_no_auth
):
    hass.config_entries.async_update_entry(account, options={"live_enabled": False})
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    client = await hass_client()
    assert (await client.get("/api/blink_plus/live/camera.test_camera")).status == 404
    assert (await client.get("/api/blink_plus/live/camera.nope")).status == 404
    anonymous = await hass_client_no_auth()
    assert (
        await anonymous.get("/api/blink_plus/live/camera.test_camera")
    ).status == 401
    blink.cameras["Test camera"].init_livestream.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_direct_live_stream_reports_a_camera_that_does_not_start(
    hass, account, blink, hass_client, socket_enabled, monkeypatch
):
    monkeypatch.setattr(
        "custom_components.blink_plus.transport.init_livestream",
        lambda camera: camera.init_livestream(),
    )
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    blink.cameras["Test camera"].init_livestream = AsyncMock(side_effect=OSError)
    client = await hass_client()
    response = await client.get("/api/blink_plus/live/camera.test_camera")
    assert response.status == 503
    await hass.config_entries.async_unload(account.entry_id)


def adts(n):
    """A minimal ADTS AAC frame of total length n (7-byte header + payload), AAC-LC 16 kHz mono."""
    hdr = bytearray(7)
    hdr[0] = 0xFF
    hdr[1] = 0xF1
    hdr[2] = 0x60  # AAC-LC, 16 kHz
    hdr[3] = 0x40 | ((n >> 11) & 0x03)
    hdr[4] = (n >> 3) & 0xFF
    hdr[5] = ((n & 0x07) << 5) | 0x1F
    hdr[6] = 0xFC
    return bytes(hdr) + bytes(n - 7)


def test_split_adts_handles_partial_frames_and_junk():
    from custom_components.blink_plus.live_http import split_adts

    a, b = adts(20), adts(15)
    frames, rest = split_adts(
        b"\x00\x00" + a + b[:5]
    )  # leading junk + one whole + one partial
    assert frames == [a] and rest == b[:5]
    frames, rest = split_adts(rest + b[5:])  # the rest completes the second
    assert frames == [b] and rest == b""


async def test_talk_view_speaks_adts_through_the_open_session(
    hass, account, blink, hass_client, socket_enabled
):
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    relay = account.runtime_data.relay(blink.cameras["Test camera"])

    class Writer:
        def __init__(self):
            self.data = bytearray()

        def is_closing(self):
            return False

        def write(self, b):
            self.data += b

        async def drain(self):
            relay.talk_ack.set()

    writer = Writer()
    relay.stream = SimpleNamespace(target_writer=writer)
    client = await hass_client()
    body = adts(30) + adts(22)
    r = await client.post("/api/blink_plus/talk/camera.test_camera", data=body)
    assert r.status == 200 and (await r.json())["frames"] == 2
    # Opens the speaker (0x17), carries the two ADTS frames as 0x05 packets, closes it (0x17).
    assert writer.data[0] == 0x17 and writer.data.count(b"\xff\xf1") == 2
    assert writer.data[-9] == 0x17

    # Another upload cannot reset this speaker or stop its owner.
    await relay.talk_lock.acquire()
    before = bytes(writer.data)
    r = await client.post("/api/blink_plus/talk/camera.test_camera", data=body)
    assert r.status == 409 and bytes(writer.data) == before
    relay.talk_lock.release()

    # Invalid codec settings and truncated frames are rejected.
    invalid = bytearray(adts(20))
    invalid[2] = 0x4C  # AAC-LC at 48 kHz.
    for payload in (bytes(invalid), adts(20)[:-1], b""):
        r = await client.post("/api/blink_plus/talk/camera.test_camera", data=payload)
        assert r.status == 400

    # No session open -> refused.
    relay.stream = None
    r = await client.post("/api/blink_plus/talk/camera.test_camera", data=adts(20))
    assert r.status == 503
    await hass.config_entries.async_unload(account.entry_id)


async def test_talk_timeout_releases_speaker_and_lock(
    hass, account, blink, hass_client, socket_enabled, monkeypatch
):
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    relay = account.runtime_data.relay(blink.cameras["Test camera"])
    stream = SimpleNamespace()
    relay.stream = stream

    async def slow_start():
        import asyncio

        await asyncio.sleep(0.05)

    relay.start_talk = AsyncMock(side_effect=slow_start)
    relay.stop_talk = AsyncMock()
    monkeypatch.setattr("custom_components.blink_plus.live_http.TALK_TIMEOUT", 0.01)

    client = await hass_client()
    response = await client.post(
        "/api/blink_plus/talk/camera.test_camera", data=adts(20)
    )
    assert response.status == 408
    relay.stop_talk.assert_awaited_once()
    assert not relay.talk_lock.locked()
    relay.stream = None
    await hass.config_entries.async_unload(account.entry_id)


async def test_old_talk_upload_cannot_write_to_or_stop_new_session(
    hass, account, blink, hass_client, socket_enabled
):
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    relay = account.runtime_data.relay(blink.cameras["Test camera"])
    relay.stream = SimpleNamespace()
    replacement = SimpleNamespace()

    async def replace_session():
        relay.stream = replacement

    relay.start_talk = AsyncMock(side_effect=replace_session)
    relay.send_audio = AsyncMock()
    relay.stop_talk = AsyncMock()
    client = await hass_client()
    response = await client.post(
        "/api/blink_plus/talk/camera.test_camera", data=adts(20)
    )
    assert response.status == 503
    relay.send_audio.assert_not_awaited()
    relay.stop_talk.assert_not_awaited()
    relay.stream = None
    await hass.config_entries.async_unload(account.entry_id)
