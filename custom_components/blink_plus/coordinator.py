"""Blink Plus account coordinator."""

from datetime import timedelta
from copy import deepcopy
import asyncio
from pathlib import Path
from functools import partial
from datetime import datetime, timezone
from uuid import uuid4

from aiohttp import ClientError
from blinkpy.auth import (
    Auth,
    UnauthorizedError,
    TokenRefreshFailed,
    LoginError,
    BlinkTwoFARequiredError,
)
from blinkpy.blinkpy import Blink
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import logging

from .const import DEFAULTS, DOMAIN
from .transport import NativeRelay
from .cloud import CloudClips

AUTH_ERRORS = (
    UnauthorizedError,
    TokenRefreshFailed,
    LoginError,
    BlinkTwoFARequiredError,
)
# Blink runs one command at a time per network and answers "busy" meanwhile.
SNAPSHOT_ATTEMPTS = 3
SNAPSHOT_BUSY_SECONDS = 6
SNAPSHOT_POLL_SECONDS = 3
SNAPSHOT_WAIT_SECONDS = 45


def blink_busy(result):
    """Blink accepted nothing: another command is still running on this network."""
    return (
        isinstance(result, dict)
        and "id" not in result
        and (
            result.get("code") == 307
            or "busy" in str(result.get("message", "")).lower()
        )
    )


def listed_thumbnail(homescreen, camera):
    """The camera's current thumbnail in Blink's one-request overview, if listed there."""
    camera_id = getattr(camera, "camera_id", None)
    if camera_id is None or not isinstance(homescreen, dict):
        return None
    for devices in homescreen.values():
        if not isinstance(devices, list):
            continue
        for device in devices:
            if (
                isinstance(device, dict)
                and str(device.get("id")) == str(camera_id)
                and device.get("name") == camera.name
                and device.get("thumbnail")
            ):
                return device["thumbnail"]
    return None


def token_data(auth):
    """Persist tokens/device identity; never retain a user's password or MFA code."""
    return {
        k: v
        for k, v in auth.login_attributes.items()
        if k not in {"password", "pin", "code"}
    }


class BlinkCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        self.entry = entry
        self.options = {**DEFAULTS, **entry.options}
        self.api = Blink(
            session=async_get_clientsession(hass),
            refresh_rate=self.options["scan_interval"],
        )
        self.api.auth = Auth(
            deepcopy(dict(entry.data)),
            no_prompt=True,
            session=async_get_clientsession(hass),
            callback=self.save_tokens,
        )
        self.cloud = CloudClips(hass, self.api, self.options, self.auth_error)
        self.relays = {}
        self.camera_entities = {}
        self.recording = set()
        self.local_recordings = {}
        self.control_lock = asyncio.Lock()
        super().__init__(
            hass,
            logging.getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=self.options["scan_interval"]),
            config_entry=entry,
        )

    def save_tokens(self):
        self.hass.config_entries.async_update_entry(
            self.entry, data=token_data(self.api.auth)
        )

    def auth_error(self, error):
        if isinstance(error, AUTH_ERRORS):
            self.entry.async_start_reauth(self.hass)

    async def _async_update_data(self):
        try:
            async with asyncio.timeout(60):
                if not self.api.available:
                    if not await self.api.start():
                        raise ConfigEntryAuthFailed("Blink login was rejected")
                else:
                    await self.api.refresh()
        except AUTH_ERRORS as err:
            raise ConfigEntryAuthFailed("Blink authentication expired") from err
        except (ClientError, TimeoutError, OSError) as err:
            raise UpdateFailed("Cannot reach Blink") from err
        return {str(c.serial): c.attributes for c in self.api.cameras.values()}

    def relay(self, camera):
        key = str(camera.serial)
        if key not in self.relays:
            self.relays[key] = NativeRelay(
                camera,
                self.options["max_live_seconds"],
                self.options["reconnect_cooldown"],
                self.auth_error,
            )
        return self.relays[key]

    async def command(self, operation, *args, timeout=60):
        """Serialize requests and their refresh; keep upstream details out of UI errors."""
        async with self.control_lock:
            try:
                async with asyncio.timeout(timeout):
                    result = await operation(*args)
                    if (
                        result is False
                        or result is None
                        or getattr(result, "status", 200) >= 400
                    ):
                        raise HomeAssistantError("Blink did not accept the request")
                    await self.api.refresh(force=True)
            except AUTH_ERRORS:
                self.entry.async_start_reauth(self.hass)
                raise HomeAssistantError("Blink authentication expired") from None
            except HomeAssistantError:
                raise
            except Exception as err:
                logging.getLogger(__name__).warning(
                    "Blink command failed (%s)", type(err).__name__
                )
                raise HomeAssistantError(
                    "Blink could not complete the request"
                ) from None
            self.async_set_updated_data(
                {str(c.serial): c.attributes for c in self.api.cameras.values()}
            )
            return result

    async def snapshot(self, camera):
        """Ask for a new still and return once Blink has published it."""

        async def published():
            # One light overview request per check; a full refresh also downloads every camera's media.
            await self.api.get_homescreen()
            return listed_thumbnail(self.api.homescreen, camera)

        async def request_and_wait():
            before = await published()
            before_fallback = getattr(camera, "thumbnail", None)
            for attempt in range(SNAPSHOT_ATTEMPTS):
                result = await camera.snap_picture()
                if not blink_busy(result):
                    break
                if attempt + 1 < SNAPSHOT_ATTEMPTS:
                    await asyncio.sleep(SNAPSHOT_BUSY_SECONDS)
            else:
                raise HomeAssistantError(
                    "Blink is busy with another request; try again in a moment"
                )
            if (
                result is False
                or result is None
                or getattr(result, "status", 200) >= 400
            ):
                return result
            for _ in range(SNAPSHOT_WAIT_SECONDS // SNAPSHOT_POLL_SECONDS):
                await asyncio.sleep(SNAPSHOT_POLL_SECONDS)
                if before is not None:
                    if await published() != before:
                        await self.api.refresh(force=True)
                        return result
                else:
                    # This camera is not in the overview: compare after a full refresh instead.
                    await self.api.refresh(force=True)
                    if getattr(camera, "thumbnail", None) != before_fallback:
                        return result
            raise HomeAssistantError("Blink did not publish a fresh snapshot in time")

        await self.command(
            request_and_wait,
            timeout=SNAPSHOT_ATTEMPTS * SNAPSHOT_BUSY_SECONDS
            + SNAPSHOT_WAIT_SECONDS
            + 45,
        )

    async def record_local(self, camera):
        """Save native video/audio to HA's media directory without Blink cloud storage."""
        key = str(camera.serial)
        if not self.options["live_enabled"]:
            raise HomeAssistantError("Enable live video before recording a local clip")
        if key in self.recording:
            raise HomeAssistantError(
                "A local recording is already running for this camera"
            )
        entity = self.camera_entities.get(key)
        if entity is None:
            raise HomeAssistantError("The camera entity is unavailable")
        media_roots = self.hass.config.media_dirs
        root = self.options["recording_directory"] or (
            str(Path(next(iter(media_roots.values()))) / "blink_plus")
            if media_roots
            else ""
        )
        if not root or not Path(root).is_absolute():
            raise HomeAssistantError(
                "Choose an absolute recording folder allowed by Home Assistant"
            )
        name = f"{entity.entity_id.split('.', 1)[1]}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.mp4"
        target = Path(root) / name
        if not await self.hass.async_add_executor_job(
            self.hass.config.is_allowed_path, str(target)
        ):
            raise HomeAssistantError(
                "The recording folder must be inside Home Assistant's allowed media directories"
            )
        duration = self.options["recording_seconds"]
        if duration + 10 > self.options["max_live_seconds"]:
            raise HomeAssistantError(
                "The live-session limit must exceed the recording duration by at least 10 seconds"
            )
        stream = None
        self.recording.add(key)
        try:
            await self.hass.async_add_executor_job(
                partial(target.parent.mkdir, parents=True, exist_ok=True)
            )
            stream = await entity.async_create_stream()
            if stream is None:
                raise HomeAssistantError("Native video is unavailable")
            async with asyncio.timeout(duration + 45):
                await stream.async_record(str(target), duration=duration)
            if not await self.hass.async_add_executor_job(
                lambda: target.is_file() and target.stat().st_size > 0
            ):
                raise HomeAssistantError("No video was received for the recording")
            self.local_recordings[key] = str(target)
            entity.async_write_ha_state()
            self.hass.bus.async_fire(
                "blink_plus_recording_completed",
                {"entity_id": entity.entity_id, "path": str(target)},
            )
            return target
        except HomeAssistantError:
            raise
        except Exception as err:
            logging.getLogger(__name__).warning(
                "Blink local recording failed (%s)", type(err).__name__
            )
            raise HomeAssistantError(
                "The local recording could not be completed"
            ) from None
        finally:
            if stream and (provider := stream.outputs().get("recorder")):
                await stream.remove_provider(provider)
            self.recording.discard(key)

    async def close(self):
        await self.async_shutdown()
        await self.cloud.close()
        await asyncio.gather(*(relay.close() for relay in self.relays.values()))
