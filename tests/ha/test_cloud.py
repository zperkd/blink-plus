from test_integration import (
    account as account,
    blink as blink,
    custom_integrations as custom_integrations,
)

"""Cloud media safety, pagination, caching and authenticated HA delivery."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from custom_components.blink_plus.cloud import CloudError, media_url, catalogue_rows
from custom_components.blink_plus.media_source import BlinkMedia

BASE = "https://rest-test.immedia-semi.com"


def row(key=1, device=10, **extra):
    return {
        "id": key,
        "device_id": device,
        "device_name": "Test camera",
        "created_at": "2026-11-10T12:00:00+00:00",
        "media": f"/clips/{key}.mp4",
        "thumbnail": f"/clips/{key}.jpg",
        **extra,
    }


@pytest.mark.parametrize(
    "value",
    [
        "https://other.example/file",
        "//other.example/file",
        "file:///etc/passwd",
        "https://user:secret@rest-test.immedia-semi.com/file",
    ],
)
def test_media_origin_is_restricted(value):
    with pytest.raises(CloudError):
        media_url(BASE, value)


def test_relative_media_stays_on_origin():
    assert media_url(BASE, "/clip.mp4") == BASE + "/clip.mp4"


def test_catalogue_filters_deleted_and_invalid():
    rows = catalogue_rows(
        [row(), row(2, deleted=True), row(3, media=None), row("../bad"), None]
    )
    assert list(rows) == ["1"]
    assert rows["1"]["device_id"] == "10"


async def setup(hass, account, blink):
    assert await hass.config_entries.async_setup(account.entry_id)
    blink.urls = SimpleNamespace(base_url=BASE)
    blink.auth = SimpleNamespace(
        header={"TOKEN_AUTH": "test-secret"}, query=AsyncMock()
    )
    return account.runtime_data.cloud


async def test_pagination_and_cache(hass, account, blink):
    cloud = await setup(hass, account, blink)
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(
            side_effect=[
                {"limit": 2, "media": [row(1), row(2)]},
                {"limit": 2, "media": [row(3)]},
            ]
        ),
    ) as request:
        assert len(await cloud.list()) == 3
        assert len(await cloud.list()) == 3
        assert request.await_count == 2
    await hass.config_entries.async_unload(account.entry_id)


async def test_repeated_page_stops(hass, account, blink):
    cloud = await setup(hass, account, blink)
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(return_value={"limit": 1, "media": [row()]}),
    ) as request:
        assert len(await cloud.list()) == 1
        assert request.await_count == 2
    await hass.config_entries.async_unload(account.entry_id)


async def test_disabled_cloud_does_not_fetch(hass, account, blink):
    cloud = await setup(hass, account, blink)
    cloud.options["cloud_enabled"] = False
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos", new=AsyncMock()
    ) as request:
        with pytest.raises(CloudError):
            await cloud.list()
        request.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


class Response:
    status = 200

    def __init__(self):
        self.content = self
        self.release = MagicMock()

    async def iter_chunked(self, size):
        yield b"\0\0\0\x18ftypmp42test-mp4-content"


async def test_media_download_cache_and_unload(hass, account, blink):
    cloud = await setup(hass, account, blink)
    blink.auth.query = AsyncMock(return_value=Response())
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(return_value={"limit": 200, "media": [row()]}),
    ):
        path1, path2 = await asyncio.gather(cloud.file("1"), cloud.file("1"))
        assert path1 == path2 and path1.is_file()
        blink.auth.query.assert_awaited_once()
        assert blink.auth.query.call_args.kwargs["headers"] == {
            "TOKEN_AUTH": "test-secret"
        }
    directory = path1.parent
    await hass.config_entries.async_unload(account.entry_id)
    assert not directory.exists()


async def test_bad_origin_never_gets_auth_header(hass, account, blink):
    cloud = await setup(hass, account, blink)
    blink.auth.query = AsyncMock()
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(
            return_value={
                "limit": 200,
                "media": [row(media="https://other.example/clip.mp4")],
            }
        ),
    ):
        with pytest.raises(CloudError):
            await cloud.file("1")
        blink.auth.query.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_cloud_http_requires_auth(hass, account, blink, hass_client_no_auth):
    await setup(hass, account, blink)
    client = await hass_client_no_auth()
    response = await client.get(f"/api/blink_plus/{account.entry_id}/video/1")
    assert response.status == 401
    await hass.config_entries.async_unload(account.entry_id)


async def test_cloud_http_supports_range(hass, account, blink, hass_client):
    await setup(hass, account, blink)
    blink.auth.query = AsyncMock(return_value=Response())
    client = await hass_client()
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(return_value={"limit": 200, "media": [row()]}),
    ):
        response = await client.get(
            f"/api/blink_plus/{account.entry_id}/video/1",
            headers={"Range": "bytes=0-7"},
        )
        assert response.status == 206
        assert len(await response.read()) == 8
        assert response.headers["Content-Type"] == "video/mp4"
    await hass.config_entries.async_unload(account.entry_id)


async def test_media_browser_uses_signed_ha_urls(hass, account, blink):
    await setup(hass, account, blink)
    source = BlinkMedia(hass)
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(return_value={"limit": 200, "media": [row()]}),
    ):
        folder = await source.async_browse_media(
            SimpleNamespace(identifier=account.entry_id + "/10")
        )
        assert len(folder.children) == 1
        media = await source.async_resolve_media(
            SimpleNamespace(identifier=account.entry_id + "/10/1")
        )
        assert media.url.startswith("/api/blink_plus/") and "authSig=" in media.url
        assert BASE not in media.url and "test-secret" not in media.url
    await hass.config_entries.async_unload(account.entry_id)


async def test_unload_cancels_active_cloud_download(hass, account, blink):
    cloud = await setup(hass, account, blink)
    entered = asyncio.Event()

    class Slow(Response):
        async def iter_chunked(self, size):
            entered.set()
            await asyncio.sleep(60)
            yield b"not reached"

    response = Slow()
    blink.auth.query = AsyncMock(return_value=response)
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(return_value={"limit": 200, "media": [row()]}),
    ):
        task = asyncio.create_task(cloud.file("1"))
        await asyncio.wait_for(entered.wait(), 2)
        directory = Path(cloud.temp.name)
        await asyncio.wait_for(hass.config_entries.async_unload(account.entry_id), 2)
        assert task.cancelled()
        response.release.assert_called_once()
        assert not directory.exists()


async def test_configured_cache_limit_rejects_large_download(hass, account, blink):
    cloud = await setup(hass, account, blink)
    cloud.options["cloud_cache_mb"] = 16

    class Large(Response):
        async def iter_chunked(self, size):
            for _ in range(257):
                yield b"x" * 65536

    response = Large()
    blink.auth.query = AsyncMock(return_value=response)
    with patch(
        "custom_components.blink_plus.cloud.api.request_videos",
        new=AsyncMock(return_value={"limit": 200, "media": [row()]}),
    ):
        with pytest.raises(CloudError, match="size limit"):
            await cloud.file("1")
    directory = Path(cloud.temp.name)
    assert not list(directory.iterdir())
    response.release.assert_called_once()
    await hass.config_entries.async_unload(account.entry_id)
    assert not directory.exists()
