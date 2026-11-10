"""Opt-in live test on the development Pi; never runs in normal tests or CI."""

import asyncio
import json
import os
from pathlib import Path
import time
import pytest
from aiohttp import ClientSession, TCPConnector, ThreadedResolver
from unittest.mock import patch
from pytest_homeassistant.common import MockConfigEntry

pytestmark = pytest.mark.skipif(
    os.environ.get("BLINK_PLUS_LIVE_TEST") != "1",
    reason="Explicit live-test opt in required",
)


@pytest.mark.parametrize(
    "camera_id", os.environ.get("BLINK_PLUS_LIVE_CAMERA_IDS", "").split(",")
)
async def test_live_native_decode(
    hass, enable_custom_integrations, socket_enabled, monkeypatch, camera_id
):
    import pytest_socket

    pytest_socket.socket_allow_hosts(["0.0.0.0/0", "::/0"], allow_unix_socket=True)
    from pytest_homeassistant import plugins

    monkeypatch.setattr("socket.getaddrinfo", plugins._real_getaddrinfo)
    raw = json.loads(Path(os.environ["BLINK_PLUS_AUTH_FILE"]).read_text())
    entry = MockConfigEntry(
        domain="blink_plus",
        title="Live test",
        unique_id="live-test",
        data=raw,
        options={"max_live_seconds": 30, "reconnect_cooldown": 5},
    )
    entry.add_to_hass(hass)
    session = ClientSession(connector=TCPConnector(resolver=ThreadedResolver()))
    try:
        with patch(
            "custom_components.blink_plus.coordinator.async_get_clientsession",
            return_value=session,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        api_camera = next(
            c
            for c in entry.runtime_data.api.cameras.values()
            if str(c.camera_id) == camera_id
        )
        component = hass.data["camera"]
        camera = next(
            c for c in component.entities if getattr(c, "camera", None) is api_camera
        )
        t = time.perf_counter()
        stream = await camera.async_create_stream()
        assert entry.runtime_data.relay(api_camera).starts == 0
        jpeg = await asyncio.wait_for(
            stream.async_get_image(wait_for_next_keyframe=True), 25
        )
        elapsed = time.perf_counter() - t
        assert jpeg and jpeg.startswith(b"\xff\xd8")
        print(
            "LIVE_DECODE camera_id="
            + camera_id
            + " first_decoded_frame_s="
            + str(round(elapsed, 3))
            + " jpeg_bytes="
            + str(len(jpeg)),
            flush=True,
        )
        for provider in list(stream.outputs().values()):
            await stream.remove_provider(provider)
        await stream.stop()
    finally:
        if getattr(entry, "runtime_data", None):
            await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        await session.close()
        await asyncio.sleep(0.25)
