"""Explicit real-device controls test; restore arming, motion and mount position."""

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import patch
import pytest
from aiohttp import ClientSession, TCPConnector, ThreadedResolver
from pytest_homeassistant.common import MockConfigEntry

pytestmark = pytest.mark.skipif(
    os.environ.get("BLINK_PLUS_CONTROL_TEST") != "1",
    reason="Explicit physical-control test opt in required",
)


async def test_supported_controls(
    hass, enable_custom_integrations, socket_enabled, monkeypatch
):
    import pytest_socket
    from pytest_homeassistant import plugins

    pytest_socket.socket_allow_hosts(["0.0.0.0/0", "::/0"], allow_unix_socket=True)
    monkeypatch.setattr("socket.getaddrinfo", plugins._real_getaddrinfo)
    raw = json.loads(
        Path(os.environ["BLINK_PLUS_AUTH_FILE"]).read_text(encoding="utf-8")
    )
    session = ClientSession(connector=TCPConnector(resolver=ThreadedResolver()))
    recording_root = Path(__file__).resolve().parents[2] / ".validation" / "recordings"
    hass.config.allowlist_external_dirs.add(str(recording_root))
    entry = MockConfigEntry(
        domain="blink_plus",
        title="Controls validation",
        unique_id="controls-validation",
        data=raw,
        options={
            "max_live_seconds": 120,
            "reconnect_cooldown": 5,
            "pan_step": 5,
            "tilt_step": 5,
            "recording_seconds": 15,
            "recording_directory": str(recording_root),
        },
    )
    entry.add_to_hass(hass)
    results = []

    def record(name, **details):
        item = {"test": name, **details}
        results.append(item)
        print("CONTROL_RESULT " + json.dumps(item), flush=True)

    try:
        with patch(
            "custom_components.blink_plus.coordinator.async_get_clientsession",
            return_value=session,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        co = entry.runtime_data
        by_name = {c.name: c for c in co.api.cameras.values()}
        garage = next(
            c
            for c in by_name.values()
            if str(c.camera_id) == os.environ["BLINK_PLUS_CONTROL_MINI_ID"]
        )
        # Fresh snapshots through the real HA button service.
        for ident in os.environ["BLINK_PLUS_LIVE_CAMERA_IDS"].split(","):
            camera = next(
                c for c in co.api.cameras.values() if str(c.camera_id) == ident
            )
            button = next(
                b
                for b in hass.data["button"].entities
                if getattr(b, "camera", None) is camera and b.action == "snapshot"
            )
            before = camera.thumbnail
            t = time.perf_counter()
            await hass.services.async_call(
                "button", "press", {"entity_id": button.entity_id}, blocking=True
            )
            assert camera.thumbnail != before
            assert camera.image_from_cache and camera.image_from_cache.startswith(
                b"\xff\xd8"
            )
            record(
                "fresh_snapshot",
                camera=camera.name,
                seconds=round(time.perf_counter() - t, 2),
            )
        if os.environ.get("BLINK_PLUS_SNAPSHOTS_ONLY") == "1":
            return
        # Restore the original motion setting even if assertions fail.
        motion = next(
            s
            for s in hass.data["switch"].entities
            if getattr(s, "camera", None) is garage
        )
        original = bool(garage.motion_enabled)
        try:
            await hass.services.async_call(
                "switch",
                "turn_off" if original else "turn_on",
                {"entity_id": motion.entity_id},
                blocking=True,
            )
            await co.api.refresh(force=True)
            assert bool(garage.motion_enabled) is not original
            record("motion_toggle", camera=garage.name, verified=True)
        finally:
            await hass.services.async_call(
                "switch",
                "turn_on" if original else "turn_off",
                {"entity_id": motion.entity_id},
                blocking=True,
            )
            await co.api.refresh(force=True)
            assert bool(garage.motion_enabled) is original
            record("motion_restored", camera=garage.name, state=original)
        # One network arming transition, followed immediately by restoration.
        for switch in [s for s in hass.data["switch"].entities if hasattr(s, "sync")]:
            original = bool(switch.sync.arm)
            try:
                await hass.services.async_call(
                    "switch",
                    "turn_off" if original else "turn_on",
                    {"entity_id": switch.entity_id},
                    blocking=True,
                )
                await co.api.refresh(force=True)
                assert bool(switch.sync.arm) is not original
                record("network_arm_toggle", verified=True)
            finally:
                for attempt in range(3):
                    try:
                        await hass.services.async_call(
                            "switch",
                            "turn_on" if original else "turn_off",
                            {"entity_id": switch.entity_id},
                            blocking=True,
                        )
                        await co.api.refresh(force=True)
                        if bool(switch.sync.arm) is original:
                            break
                    except Exception:
                        if attempt == 2:
                            raise
                    await asyncio.sleep(2)
                assert bool(switch.sync.arm) is original
                record("network_arm_restored", state=original)
        # Verify actual accessory acknowledgements, then restore the original view.
        bedroom = next(
            c
            for c in co.api.cameras.values()
            if str(c.camera_id) == os.environ["BLINK_PLUS_CONTROL_PTZ_ID"]
        )
        relay = co.relay(bedroom)
        source = await relay.source()
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", int(source.rsplit(":", 1)[1])
        )

        async def consume():
            while await reader.read(65536):
                pass

        consumer = asyncio.create_task(consume())
        origin = None

        async def wait_position(expected=None, after=-1):
            for _ in range(150):
                stream = relay.stream
                if (
                    stream
                    and getattr(stream, "position_version", 0) > after
                    and not getattr(stream, "mount_moving", False)
                ):
                    position = getattr(stream, "position", None)
                    if position and (expected is None or position == expected):
                        return dict(position)
                await asyncio.sleep(0.1)
            raise AssertionError("Mount did not acknowledge the expected position")

        async def absolute(position):
            stream = relay.stream
            version = getattr(stream, "position_version", 0)
            payload = (
                b"\0" * 4
                + position["pan"].to_bytes(1, "big", signed=True)
                + position["tilt"].to_bytes(1, "big", signed=True)
                + b"\0"
            )
            stream.target_writer.write(
                b"\x14"
                + (3).to_bytes(4, "big")
                + len(payload).to_bytes(4, "big")
                + payload
            )
            await stream.target_writer.drain()
            return await wait_position(position, version)

        try:
            origin = await wait_position()
            for action in ("left", "right", "up", "down"):
                stream = relay.stream
                version = getattr(stream, "position_version", 0)
                await relay.pan_tilt(action, pan_step=5, tilt_step=5)
                expected = dict(stream.position)
                await wait_position(expected, version)
                record("pan_tilt_" + action, acknowledged=True)
            version = getattr(relay.stream, "position_version", 0)
            await relay.pan_tilt("home")
            await wait_position(after=version)
            record("pan_tilt_home", acknowledged=True)
        finally:
            if origin:
                await absolute(origin)
                record("pan_tilt_restored", verified=True)
            writer.close()
            await writer.wait_closed()
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)
            await relay.close()
        # Save a local MP4 through the HA button; cloud clip browsing is tested separately.
        button = next(
            b
            for b in hass.data["button"].entities
            if getattr(b, "camera", None) is garage and b.action == "record"
        )
        await hass.services.async_call(
            "button", "press", {"entity_id": button.entity_id}, blocking=True
        )
        filename = Path(co.local_recordings[str(garage.serial)])
        assert filename.is_file() and filename.stat().st_size > 1000
        record("record_local_clip", camera=garage.name, verified=True)
    finally:
        if getattr(entry, "runtime_data", None):
            await hass.config_entries.async_unload(entry.entry_id)
        await session.close()
        await asyncio.sleep(0.25)
        await hass.async_block_till_done()
        folder = Path(__file__).resolve().parents[2] / ".validation"
        folder.mkdir(exist_ok=True)
        (
            folder
            / (
                "snapshots.json"
                if os.environ.get("BLINK_PLUS_SNAPSHOTS_ONLY") == "1"
                else "controls.json"
            )
        ).write_text(json.dumps(results, indent=2), encoding="utf-8")
