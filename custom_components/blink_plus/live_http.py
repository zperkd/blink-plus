"""Direct native live video over HTTP for low-delay players.

Home Assistant's own live view repackages the camera's video as HLS, which adds
a second or more of delay. This view hands an authenticated client the camera's
native MPEG-TS (H.264 + AAC) as it arrives. It is one more viewer of the
camera's relay, so session limits, cooldown and sharing apply unchanged, and the
camera session ends as soon as the last viewer disconnects.
"""

import asyncio
from contextlib import suppress

from aiohttp import web
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState

from .const import DOMAIN

START_TIMEOUT = 30
MAX_ADTS = 8192
TALK_TIMEOUT = 60
# ADTS sampling-frequency-index -> Hz; an AAC frame is 1024 samples, so its duration is 1024 / rate seconds.
ADTS_RATES = (
    96000,
    88200,
    64000,
    48000,
    44100,
    32000,
    24000,
    22050,
    16000,
    12000,
    11025,
    8000,
    7350,
    0,
    0,
    0,
)


def adts_duration(frame):
    """Playback duration of one ADTS AAC frame, in seconds (default 16 kHz)."""
    rate = ADTS_RATES[(frame[2] >> 2) & 0x0F] if len(frame) > 2 else 0
    return 1024 / (rate or 16000)


def split_adts(buf):
    """Split a byte buffer into complete ADTS AAC frames; return (frames, unconsumed remainder)."""
    frames = []
    i = 0
    n = len(buf)
    while True:
        while i + 7 <= n and not (buf[i] == 0xFF and (buf[i + 1] & 0xF0) == 0xF0):
            i += 1  # resync to the next 0xFFFx sync word
        if i + 7 > n:
            return frames, buf[i:]
        length = ((buf[i + 3] & 0x03) << 11) | (buf[i + 4] << 3) | (buf[i + 5] >> 5)
        if length < 7 or length > MAX_ADTS:
            i += 1
            continue
        if i + length > n:
            return frames, buf[i:]
        frames.append(buf[i : i + length])
        i += length


def find_relay(hass, entity_id):
    """The relay of a loaded, live-enabled Blink Plus camera entity."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator = entry.runtime_data
        if not coordinator.options["live_enabled"]:
            continue
        for entity in coordinator.camera_entities.values():
            if entity.entity_id == entity_id:
                return coordinator.relay(entity.camera)
    return None


class BlinkLiveView(HomeAssistantView):
    url = "/api/blink_plus/live/{entity_id}"
    name = "api:blink_plus:live"
    requires_auth = True

    async def get(self, request, entity_id):
        hass = request.app[KEY_HASS]
        user = request.get("hass_user")
        if user is not None and not user.permissions.check_entity(
            entity_id, POLICY_READ
        ):
            raise web.HTTPForbidden
        relay = find_relay(hass, entity_id)
        if relay is None:
            raise web.HTTPNotFound(text="Unknown Blink Plus camera")
        try:
            port = int((await relay.source()).rsplit(":", 1)[1])
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except (OSError, RuntimeError):
            raise web.HTTPServiceUnavailable(text="Live view is unavailable") from None
        response = web.StreamResponse(
            headers={"Content-Type": "video/mp2t", "Cache-Control": "no-store"}
        )
        try:
            # No bytes at all: the relay refused (cooldown) or the camera did not start.
            try:
                first = await asyncio.wait_for(reader.read(65536), START_TIMEOUT)
            except TimeoutError:
                first = b""
            if not first:
                raise web.HTTPServiceUnavailable(
                    text="The camera did not start; try again in a moment"
                )
            await response.prepare(request)
            await response.write(first)
            while chunk := await reader.read(65536):
                await response.write(chunk)
        except (ConnectionError, OSError):
            pass  # The viewer went away.
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
        return response


class BlinkTalkView(HomeAssistantView):
    """Receive a stream of ADTS AAC frames and speak them through the open live session (two-way talk)."""

    url = "/api/blink_plus/talk/{entity_id}"
    name = "api:blink_plus:talk"
    requires_auth = True

    async def post(self, request, entity_id):
        hass = request.app[KEY_HASS]
        user = request.get("hass_user")
        if user is not None and not user.permissions.check_entity(
            entity_id, POLICY_CONTROL
        ):
            raise web.HTTPForbidden
        relay = find_relay(hass, entity_id)
        if relay is None or relay.stream is None:
            raise web.HTTPServiceUnavailable(text="Open live view before talking")
        if relay.talk_lock.locked():
            raise web.HTTPConflict(text="Someone is already talking to this camera")
        async with relay.talk_lock:
            stream = relay.stream
            loop = asyncio.get_running_loop()
            buf = b""
            sent = 0
            clock = None
            try:
                async with asyncio.timeout(TALK_TIMEOUT):
                    await relay.start_talk()
                    async for chunk in request.content.iter_chunked(8192):
                        buf += chunk
                        frames, buf = split_adts(buf)
                        for frame in frames:
                            # AAC-LC, 16 kHz, mono, one 1024-sample block per frame.
                            channels = ((frame[2] & 1) << 2) | (frame[3] >> 6)
                            header_size = 7 if frame[1] & 1 else 9
                            if (
                                frame[1] & 6
                                or frame[2] >> 6 != 1
                                or (frame[2] >> 2) & 15 != 8
                                or channels != 1
                                or frame[6] & 3
                                or len(frame) < header_size
                            ):
                                raise web.HTTPBadRequest(
                                    text="Expected AAC-LC, 16 kHz, mono ADTS audio"
                                )
                            now = loop.time()
                            if clock is None or clock < now - 0.5:
                                clock = now
                            elif clock > now:
                                await asyncio.sleep(clock - now)
                            if relay.stream is not stream:
                                raise RuntimeError("Live view changed")
                            await relay.send_audio(frame)
                            sent += 1
                            clock += adts_duration(frame)
                    if buf or not sent:
                        raise web.HTTPBadRequest(text="Empty or incomplete ADTS audio")
            except TimeoutError:
                raise web.HTTPRequestTimeout(
                    text="Talk exceeded its time limit"
                ) from None
            except RuntimeError:
                raise web.HTTPServiceUnavailable(
                    text="Live view closed or talk was not acknowledged"
                ) from None
            except (ConnectionError, OSError):
                pass
            finally:
                # An old upload must never stop a replacement live session.
                if relay.stream is stream:
                    with suppress(Exception):
                        await relay.stop_talk()
            return web.json_response({"frames": sent})
