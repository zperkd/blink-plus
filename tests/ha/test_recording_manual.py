"""Explicit opt-in native local recording test with real cameras and MP4 decoding."""

import asyncio, json, os, time
from pathlib import Path
from unittest.mock import patch
import pytest
from aiohttp import ClientSession, TCPConnector, ThreadedResolver
from pytest_homeassistant.common import MockConfigEntry

pytestmark = pytest.mark.skipif(
    os.environ.get("BLINK_PLUS_RECORD_TEST") != "1",
    reason="Explicit recording-test opt in required",
)


@pytest.mark.parametrize(
    "camera_id", os.environ.get("BLINK_PLUS_LIVE_CAMERA_IDS", "").split(",")
)
async def test_local_mp4(
    hass, enable_custom_integrations, socket_enabled, monkeypatch, camera_id
):
    import pytest_socket
    from pytest_homeassistant import plugins

    pytest_socket.socket_allow_hosts(["0.0.0.0/0", "::/0"], allow_unix_socket=True)
    monkeypatch.setattr("socket.getaddrinfo", plugins._real_getaddrinfo)
    raw = json.loads(
        Path(os.environ["BLINK_PLUS_AUTH_FILE"]).read_text(encoding="utf-8")
    )
    root = Path(__file__).resolve().parents[2] / ".validation" / "recordings"
    hass.config.allowlist_external_dirs.add(str(root))
    entry = MockConfigEntry(
        domain="blink_plus",
        title="Recording validation",
        unique_id="record-validation",
        data=raw,
        options={
            "max_live_seconds": 90,
            "reconnect_cooldown": 5,
            "recording_directory": str(root),
            "recording_seconds": 15,
        },
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
        co = entry.runtime_data
        camera = next(
            c for c in co.api.cameras.values() if str(c.camera_id) == camera_id
        )
        button = next(
            b
            for b in hass.data["button"].entities
            if getattr(b, "camera", None) is camera and b.action == "record"
        )
        events = []
        hass.bus.async_listen_once(
            "blink_plus_recording_completed", lambda event: events.append(event.data)
        )
        t = time.perf_counter()
        await hass.services.async_call(
            "button", "press", {"entity_id": button.entity_id}, blocking=True
        )
        filename = Path(co.local_recordings[str(camera.serial)])

        def inspect_media():
            import av

            video_frames = 0
            audio_frames = 0
            with av.open(str(filename)) as container:
                codecs = [s.codec_context.name for s in container.streams]
                duration = (
                    container.duration / av.time_base if container.duration else 0
                )
                for packet in container.demux():
                    if packet.stream.type not in {"video", "audio"}:
                        continue
                    for frame in packet.decode():
                        if isinstance(frame, av.VideoFrame):
                            video_frames += 1
                        elif isinstance(frame, av.AudioFrame):
                            audio_frames += 1
            return {
                "bytes": filename.stat().st_size,
                "duration_s": round(duration, 3),
                "codecs": codecs,
                "decoded_video_frames": video_frames,
                "decoded_audio_frames": audio_frames,
            }

        result = await hass.async_add_executor_job(inspect_media)
        result.update(
            camera=camera.name,
            total_seconds=round(time.perf_counter() - t, 2),
            filename=filename.name,
        )
        print("RECORD_RESULT " + json.dumps(result), flush=True)
        (root.parent / (camera_id + "-recording.json")).write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        assert result["duration_s"] >= 10
        assert result["decoded_video_frames"] >= 100
        assert result["decoded_audio_frames"] > 0
        assert "h264" in result["codecs"] and "aac" in result["codecs"]
        assert events and events[0]["path"] == str(filename)
    finally:
        if getattr(entry, "runtime_data", None):
            await hass.config_entries.async_unload(entry.entry_id)
        await session.close()
        await asyncio.sleep(0.25)
        await hass.async_block_till_done()
