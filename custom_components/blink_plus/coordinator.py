"""Blink Plus account coordinator."""

from datetime import timedelta
from copy import deepcopy
import asyncio
from pathlib import Path
from functools import partial
from datetime import datetime, timezone
import time
from urllib.parse import urlencode
from uuid import uuid4

from aiohttp import ClientError
from blinkpy import api as blink_api
from blinkpy.auth import (
    Auth,
    UnauthorizedError,
    TokenRefreshFailed,
    LoginError,
    BlinkTwoFARequiredError,
)
from blinkpy.blinkpy import Blink, BlinkSetupError

try:
    from blinkpy.helpers.constants import (
        OAUTH_SCOPE,
        OAUTH_TOKEN_URL,
        OAUTH_TOKEN_USER_AGENT,
        OAUTH_V2_CLIENT_ID,
    )
except ImportError:  # A blinkpy without these keeps using its own startup.
    OAUTH_TOKEN_URL = None
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import logging

from .blinkpy_patches import apply_blinkpy_patches
from .const import DEFAULTS, DOMAIN
from .transport import NativeRelay
from .cloud import CloudClips

# Login form: any of these means the sign-in did not work.
AUTH_ERRORS = (
    UnauthorizedError,
    TokenRefreshFailed,
    LoginError,
    BlinkTwoFARequiredError,
)
# Running entry: only these mean Blink wants a new login. TokenRefreshFailed is
# what blinkpy raises when the token endpoint answers with anything else (an
# outage, throttling), so it is retried instead.
REAUTH_ERRORS = (UnauthorizedError, LoginError, BlinkTwoFARequiredError)
# Refresh this long before expiry, so blinkpy's own request path rarely has to.
REFRESH_MARGIN_SECONDS = 120
REFRESH_TIMEOUT_SECONDS = 30
# Blink runs one command at a time per network and answers "busy" meanwhile.
SNAPSHOT_ATTEMPTS = 3
SNAPSHOT_BUSY_SECONDS = 6
SNAPSHOT_POLL_SECONDS = 3
SNAPSHOT_WAIT_SECONDS = 45
# How far back each poll asks Blink for clips. Blink can list a clip several
# minutes after it started, so this is much longer than one poll.
CLIP_LOOKBACK_SECONDS = 1800
CLIP_TIMEOUT_SECONDS = 20


def newest_clips(rows):
    """Camera name -> start of its newest clip in one page of Blink's clip list."""
    newest = {}
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or row.get("deleted"):
            continue
        name, created = row.get("device_name"), row.get("created_at")
        if not isinstance(name, str) or not isinstance(created, str):
            continue
        try:
            when = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if name not in newest or when > newest[name]:
            newest[name] = when
    return newest


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


class TokenRejected(Exception):
    """Blink refused the stored refresh token; only a new login helps."""


class BlinkUnreachable(Exception):
    """Blink could not be reached or did not give a usable answer."""


async def refresh_tokens(auth):
    """Exchange the refresh token for new tokens; never signs in with a password.

    blinkpy's startup treats every failed refresh alike and falls back to a
    password login, which cannot work here because the password is not stored.
    Doing the exchange here tells a refused token (400/401) from an outage.
    """
    form = {
        "grant_type": "refresh_token",
        "refresh_token": auth.refresh_token,
        "client_id": OAUTH_V2_CLIENT_ID,
        "scope": OAUTH_SCOPE,
        "hardware_id": auth.hardware_id,
    }
    headers = {
        "User-Agent": OAUTH_TOKEN_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
    }
    try:
        async with asyncio.timeout(REFRESH_TIMEOUT_SECONDS):
            response = await auth.session.post(
                OAUTH_TOKEN_URL, headers=headers, data=urlencode(form)
            )
            try:
                if response.status in (400, 401):
                    raise TokenRejected
                if response.status != 200:
                    raise BlinkUnreachable(f"HTTP {response.status}")
                tokens = await response.json()
            finally:
                response.release()
        access_token = tokens["access_token"]
        expires_in = int(tokens.get("expires_in") or 3600)
        if not isinstance(access_token, str) or not access_token:
            raise ValueError
    except (ClientError, TimeoutError, OSError, ValueError, KeyError, TypeError) as err:
        # Only the class name: a response or exception text can carry tokens.
        raise BlinkUnreachable(type(err).__name__) from None
    auth.token = access_token
    auth.refresh_token = tokens.get("refresh_token") or auth.refresh_token
    auth.expires_in = expires_in
    auth.expiration_date = time.time() + expires_in


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
        # Marks this Blink instance for the load reductions in blinkpy_patches.py:
        # how often to read a Sync Module's USB clip list (0 = never).
        self.api.blink_plus_usb_clip_minutes = self.options["usb_clip_minutes"]
        self.load_reductions = apply_blinkpy_patches()
        self.cloud = CloudClips(hass, self.api, self.options, self.auth_error)
        self.relays = {}
        # Per camera serial: callbacks told the lamp state a live session reports. Kept here so a
        # light entity can listen without creating a relay (none exists while live video is off).
        self.light_listeners = {}
        self.camera_entities = {}
        self.recording = set()
        self.local_recordings = {}
        # Camera name -> start of the newest clip Blink has listed for it.
        self.clip_times = {}
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
        if isinstance(error, REAUTH_ERRORS):
            self.entry.async_start_reauth(self.hass)

    def _refreshes_own_tokens(self):
        """Whether the entry holds what the token exchange needs."""
        auth = self.api.auth
        hardware_id = getattr(auth, "hardware_id", None)
        return bool(
            OAUTH_TOKEN_URL
            and getattr(auth, "refresh_token", None)
            and hardware_id
            and hardware_id == self.entry.data.get("hardware_id")
        )

    async def _refresh_tokens(self):
        try:
            await refresh_tokens(self.api.auth)
        except TokenRejected:
            raise ConfigEntryAuthFailed("Blink rejected the stored login") from None
        except BlinkUnreachable as err:
            raise UpdateFailed(f"Cannot refresh the Blink login ({err})") from None
        self.save_tokens()

    async def _start(self):
        """Set up the Blink client; an outage is retried, not shown as a login problem."""
        api = self.api
        if not self._refreshes_own_tokens():
            # Without a refresh token only blinkpy's own startup can sign in.
            if not await api.start():
                raise ConfigEntryAuthFailed("Blink login was rejected")
            return
        await self._refresh_tokens()
        # The rest of Blink.start(), after its login step.
        try:
            api.setup_urls()
            await api.get_homescreen()
        except (BlinkSetupError, AttributeError) as err:
            # blinkpy hands back no response at all when the request failed.
            raise UpdateFailed("Blink setup failed") from err
        if not api.last_refresh:
            api.last_refresh = int(time.time() - api.refresh_rate * 1.05)
        if not await api.setup_post_verify():
            raise UpdateFailed("Blink setup failed")

    async def _async_update_data(self):
        try:
            async with asyncio.timeout(60):
                if not self.api.available:
                    await self._start()
                else:
                    expires = getattr(self.api.auth, "expiration_date", None)
                    if self._refreshes_own_tokens() and (
                        expires is None
                        or expires - time.time()
                        < self.options["scan_interval"] + REFRESH_MARGIN_SECONDS
                    ):
                        await self._refresh_tokens()
                    if self.data is not None and self.live_active():
                        # The Sync Module is busy with the live view; leave it alone.
                        return self.data
                    await self.api.refresh()
        except REAUTH_ERRORS as err:
            raise ConfigEntryAuthFailed("Blink authentication expired") from err
        except (TokenRefreshFailed, ClientError, TimeoutError, OSError) as err:
            raise UpdateFailed("Cannot reach Blink") from err
        await self.note_clips()
        return {str(c.serial): c.attributes for c in self.api.cameras.values()}

    async def note_clips(self):
        """Remember each camera's newest clip; the motion sensors compare against it.

        blinkpy only counts a clip that started after its previous refresh, so a
        clip Blink lists late, or one followed by a second refresh before Home
        Assistant is told, never showed as motion. A failed request keeps the
        earlier answer and never fails the poll.
        """
        try:
            async with asyncio.timeout(CLIP_TIMEOUT_SECONDS):
                data = await blink_api.request_videos(
                    self.api, time=int(time.time()) - CLIP_LOOKBACK_SECONDS, page=1
                )
        except Exception as err:  # noqa: BLE001 - motion is not worth a failed poll
            logging.getLogger(__name__).debug(
                "Blink clip check failed (%s)", type(err).__name__
            )
            return
        found = newest_clips(data.get("media") if isinstance(data, dict) else None)
        for name, when in found.items():
            if name not in self.clip_times or when > self.clip_times[name]:
                self.clip_times[name] = when

    def live_active(self):
        """Whether any camera of this account is starting or showing a live view."""
        return any(relay.runner is not None for relay in self.relays.values())

    def relay(self, camera):
        key = str(camera.serial)
        if key not in self.relays:
            self.relays[key] = NativeRelay(
                camera,
                self.options["max_live_seconds"],
                self.options["reconnect_cooldown"],
                self.auth_error,
            )
            self.relays[key].light_listeners = self.light_listeners.setdefault(
                key, set()
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
            except REAUTH_ERRORS:
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
            await self.note_clips()
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
