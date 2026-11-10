"""Explicit live cloud browse/play/thumbnail test through real HA media-source APIs."""

import asyncio, json, logging, os
from pathlib import Path
from unittest.mock import patch
import pytest
from aiohttp import ClientSession, TCPConnector, ThreadedResolver
from pytest_homeassistant.common import MockConfigEntry

pytestmark = pytest.mark.skipif(
    os.environ.get("BLINK_PLUS_CLOUD_TEST") != "1",
    reason="Explicit cloud-test opt in required",
)


async def test_cloud_browser_and_download(
    hass, enable_custom_integrations, socket_enabled, monkeypatch, hass_client_no_auth
):
    import pytest_socket
    from pytest_homeassistant import plugins
    from homeassistant.components.media_source import (
        async_browse_media,
        async_resolve_media,
    )

    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    pytest_socket.socket_allow_hosts(["0.0.0.0/0", "::/0"], allow_unix_socket=True)
    monkeypatch.setattr("socket.getaddrinfo", plugins._real_getaddrinfo)
    raw = json.loads(
        Path(os.environ["BLINK_PLUS_AUTH_FILE"]).read_text(encoding="utf-8")
    )
    entry = MockConfigEntry(
        domain="blink_plus",
        title="Cloud validation",
        unique_id="cloud-validation",
        data=raw,
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
        root = await async_browse_media(hass, "media-source://blink_plus")
        assert root.children
        account = await async_browse_media(hass, root.children[0].media_content_id)
        assert len(account.children) == 7
        clips = await async_browse_media(hass, account.children[0].media_content_id)
        assert clips.children
        clip = clips.children[0]
        playable = await async_resolve_media(hass, clip.media_content_id, None)
        assert playable.url.startswith("/api/blink_plus/")
        client = await hass_client_no_auth()
        denied = await client.get(playable.url.split("?")[0])
        assert denied.status == 401
        response = await client.get(playable.url, headers={"Range": "bytes=0-4095"})
        prefix = await response.read()
        assert response.status == 206 and b"ftyp" in prefix[:32]
        thumbnail = await client.get(clip.thumbnail)
        image = await thumbnail.read()
        assert thumbnail.status == 200 and image.startswith(b"\xff\xd8")
        co = entry.runtime_data
        rows = await co.cloud.list()
        key = clip.identifier.split("/")[-1]
        filename = await co.cloud.file(key)

        def inspect_file():
            import av

            with av.open(str(filename)) as video:
                return {
                    "bytes": filename.stat().st_size,
                    "duration_s": video.duration / av.time_base
                    if video.duration
                    else None,
                    "codecs": [s.codec_context.name for s in video.streams],
                }

        metadata = await hass.async_add_executor_job(inspect_file)
        result = {
            "cloud_clip_count": len(rows),
            "camera_folders": len(account.children),
            "selected_camera": account.children[0].title,
            "unsigned_request_status": denied.status,
            "signed_range_status": response.status,
            "range_bytes": len(prefix),
            "thumbnail_bytes": len(image),
            **metadata,
        }
        print("CLOUD_RESULT " + json.dumps(result), flush=True)
        folder = Path(__file__).resolve().parents[2] / ".validation"
        folder.mkdir(exist_ok=True)
        (folder / "cloud.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        assert "h264" in metadata["codecs"] and metadata["bytes"] > 1000
        directory = filename.parent
        await hass.config_entries.async_unload(entry.entry_id)
        assert not directory.exists()
    finally:
        if getattr(entry, "runtime_data", None) and entry.state.value == "loaded":
            await hass.config_entries.async_unload(entry.entry_id)
        await session.close()
        await asyncio.sleep(0.25)
        await hass.async_block_till_done()
