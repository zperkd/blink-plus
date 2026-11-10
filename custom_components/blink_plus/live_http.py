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
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState

from .const import DOMAIN

START_TIMEOUT = 30


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
