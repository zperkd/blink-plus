"""Native H.264/AAC cameras; cached stills never wake a camera."""

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from .entity import BlinkEntity

_LOGGER = logging.getLogger(__name__)


class _NoPreload:
    """HA's per-camera stream settings with stream preloading forced off.

    Preloading keeps a stream running with no viewer, which would wake an
    on-demand cloud camera again after every session limit, indefinitely.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings):
        object.__setattr__(self, "_settings", settings)

    def __getattr__(self, name):
        return False if name == "preload_stream" else getattr(self._settings, name)

    def __setattr__(self, name, value):
        if name != "preload_stream":
            setattr(self._settings, name, value)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            BlinkCamera(entry.runtime_data, c)
            for c in entry.runtime_data.api.cameras.values()
        ]
    )


class BlinkCamera(BlinkEntity, Camera):
    def __init__(self, coordinator, camera):
        Camera.__init__(self)
        BlinkEntity.__init__(self, coordinator, camera, "camera", None)
        if coordinator.options["live_enabled"]:
            self._attr_supported_features = CameraEntityFeature.STREAM

    @property
    def extra_state_attributes(self):
        path = self.coordinator.local_recordings.get(str(self.camera.serial))
        return {"last_local_recording": path} if path else None

    async def async_camera_image(self, width=None, height=None):
        return self.camera.image_from_cache

    async def stream_source(self):
        if not self.coordinator.options["live_enabled"]:
            return None
        return await self.coordinator.relay(self.camera).source()

    async def async_create_stream(self):
        stream = await super().async_create_stream()
        if stream and not isinstance(stream.dynamic_stream_settings, _NoPreload):
            if stream.dynamic_stream_settings.preload_stream:
                _LOGGER.warning(
                    "Preload stream is ignored for %s: Blink live view starts on demand",
                    self.entity_id,
                )
            stream.dynamic_stream_settings = _NoPreload(stream.dynamic_stream_settings)
        return stream

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.coordinator.camera_entities[str(self.camera.serial)] = self

    async def async_will_remove_from_hass(self):
        self.coordinator.camera_entities.pop(str(self.camera.serial), None)
        if self.stream:
            self.stream.dynamic_stream_settings.preload_stream = False
            for provider in list(self.stream.outputs().values()):
                await self.stream.remove_provider(provider)
            await self.stream.stop()
        relay = self.coordinator.relays.pop(str(self.camera.serial), None)
        if relay:
            await relay.close()
        await super().async_will_remove_from_hass()
