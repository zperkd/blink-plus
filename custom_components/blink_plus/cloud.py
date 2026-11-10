"""Bounded Blink cloud catalogue and authenticated temporary media cache."""

from __future__ import annotations
import asyncio
from functools import partial
from pathlib import Path
import tempfile
import os
import time
from urllib.parse import urljoin, urlsplit
import aiofiles
from blinkpy import api
from blinkpy.auth import (
    UnauthorizedError,
    TokenRefreshFailed,
    LoginError,
    BlinkTwoFARequiredError,
)

AUTH_ERRORS = (
    UnauthorizedError,
    TokenRefreshFailed,
    LoginError,
    BlinkTwoFARequiredError,
)
MAX_FILE_BYTES = 256 * 1024 * 1024


class CloudError(Exception):
    """A safe error that contains no upstream credential or URL."""


def media_url(base, value):
    """Only accept media paths on the authenticated Blink origin."""
    if not isinstance(value, str) or not value:
        raise CloudError("This cloud clip has no downloadable media")
    target = urlsplit(urljoin(base, value))
    origin = urlsplit(base)
    if (
        target.scheme != "https"
        or target.netloc != origin.netloc
        or target.username
        or target.password
    ):
        raise CloudError("Blink returned an unsupported media origin")
    return target.geturl()


def catalogue_rows(rows):
    result = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("deleted") or not row.get("media"):
            continue
        key = str(row.get("id", ""))
        device = str(row.get("device_id", ""))
        if not key.isdecimal() or not device.isdecimal():
            continue
        result[key] = {
            "id": key,
            "device_id": device,
            "name": str(row.get("device_name", "Camera")),
            "created_at": str(row.get("created_at", "")),
            "media": row["media"],
            "thumbnail": row.get("thumbnail"),
        }
    return result


class CloudClips:
    def __init__(self, hass, blink, options, on_auth_error):
        self.hass = hass
        self.blink = blink
        self.options = options
        self.on_auth_error = on_auth_error
        self.rows = {}
        self.updated = None
        self.lock = asyncio.Lock()
        self.file_locks = {}
        self.temp = None
        self.closed = False
        self.transfers = asyncio.Semaphore(2)
        self.cache_lock = asyncio.Lock()
        self.tasks = set()

    async def list(self, force=False):
        if self.closed or not self.options["cloud_enabled"]:
            raise CloudError("Cloud clips are disabled")
        async with self.lock:
            if (
                not force
                and self.updated is not None
                and time.monotonic() - self.updated
                < self.options["cloud_refresh_seconds"]
            ):
                return self.rows
            result = {}
            seen = set()
            maximum = self.options["cloud_max_clips"]
            since = int(time.time()) - self.options["cloud_history_days"] * 86400
            try:
                async with asyncio.timeout(60):
                    for page in range(1, 27):
                        data = await api.request_videos(
                            self.blink, time=since, page=page
                        )
                        if not isinstance(data, dict) or not isinstance(
                            data.get("media"), list
                        ):
                            raise CloudError("Blink cloud clips could not be listed")
                        rows = data["media"]
                        ids = {str(r.get("id")) for r in rows if isinstance(r, dict)}
                        if not rows or not ids - seen:
                            break
                        seen.update(ids)
                        result.update(catalogue_rows(rows))
                        if len(result) >= maximum or len(rows) < data.get("limit", 200):
                            break
            except AUTH_ERRORS as err:
                self.on_auth_error(err)
                raise CloudError("Blink needs authentication again") from None
            except CloudError:
                raise
            except Exception:
                raise CloudError(
                    "Blink cloud clips are temporarily unavailable"
                ) from None
            self.rows = dict(
                sorted(
                    result.items(), key=lambda item: item[1]["created_at"], reverse=True
                )[:maximum]
            )
            self.updated = time.monotonic()
            return self.rows

    async def lookup(self, clip_id):
        if not str(clip_id).isdecimal():
            raise CloudError("Unknown cloud clip")
        rows = await self.list()
        if str(clip_id) not in rows:
            raise CloudError("This cloud clip is no longer in the catalogue")
        return rows[str(clip_id)]

    async def file(self, clip_id, thumbnail=False):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with self.transfers:
                return await self._file(clip_id, thumbnail)
        finally:
            self.tasks.discard(task)

    async def _file(self, clip_id, thumbnail=False):
        row = await self.lookup(clip_id)
        key = str(clip_id) + ("t" if thumbnail else "v")
        lock = self.file_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if self.closed:
                raise CloudError("Cloud clips are unloaded")
            if self.temp is None:
                # Serialize directory creation across different clip requests.
                async with self.lock:
                    if self.temp is None:
                        self.temp = await self.hass.async_add_executor_job(
                            partial(tempfile.TemporaryDirectory, prefix="blink_plus_")
                        )
            target = Path(self.temp.name) / (
                str(clip_id) + (".jpg" if thumbnail else ".mp4")
            )
            if await self.hass.async_add_executor_job(target.is_file):
                await self.hass.async_add_executor_job(os.utime, target, None)
                return target
            url = media_url(
                self.blink.urls.base_url,
                row["thumbnail"] if thumbnail else row["media"],
            )
            pending = target.with_suffix(target.suffix + ".part")
            response = None
            try:
                async with asyncio.timeout(90):
                    response = await self.blink.auth.query(
                        url=url,
                        headers=self.blink.auth.header,
                        reqtype="get",
                        stream=True,
                        json_resp=False,
                    )
                    if response is None or response.status != 200:
                        raise CloudError("Blink did not return this media")
                    size = 0
                    async with aiofiles.open(pending, "wb") as output:
                        async for chunk in response.content.iter_chunked(65536):
                            size += len(chunk)
                            if size > min(
                                MAX_FILE_BYTES,
                                self.options["cloud_cache_mb"] * 1024 * 1024,
                            ):
                                raise CloudError(
                                    "This clip exceeds the download size limit"
                                )
                            await output.write(chunk)
                    if not size:
                        raise CloudError("Blink returned an empty media file")
                    await self.hass.async_add_executor_job(pending.replace, target)
                async with self.cache_lock:
                    await self.hass.async_add_executor_job(self._evict, target)
                return target
            except AUTH_ERRORS as err:
                self.on_auth_error(err)
                raise CloudError("Blink needs authentication again") from None
            except CloudError:
                raise
            except Exception:
                raise CloudError("This cloud clip could not be downloaded") from None
            finally:
                if response is not None:
                    response.release()
                await self.hass.async_add_executor_job(
                    partial(pending.unlink, missing_ok=True)
                )

    def _evict(self, keep):
        files = [
            p for p in Path(self.temp.name).iterdir() if p.suffix in {".jpg", ".mp4"}
        ]
        total = sum(p.stat().st_size for p in files)
        limit = self.options["cloud_cache_mb"] * 1024 * 1024
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            if total <= limit:
                break
            if path == keep:
                continue
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size

    async def close(self):
        self.closed = True
        tasks = [
            task for task in tuple(self.tasks) if task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Let active downloads release their file handles before removing our own temp directory.
        for lock in tuple(self.file_locks.values()):
            async with lock:
                pass
        if self.temp:
            await self.hass.async_add_executor_job(self.temp.cleanup)
            self.temp = None
        self.rows.clear()
