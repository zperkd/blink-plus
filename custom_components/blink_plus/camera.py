"""Native H.264/AAC cameras; cached stills never wake a camera."""

from homeassistant.components.camera import Camera, CameraEntityFeature
from .entity import BlinkEntity


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

    async def async_will_remove_from_hass(self):
        if self.stream:
            self.stream.dynamic_stream_settings.preload_stream = False
            for provider in list(self.stream.outputs().values()):
                await self.stream.remove_provider(provider)
            await self.stream.stop()
        relay = self.coordinator.relays.pop(str(self.camera.serial), None)
        if relay:
            await relay.close()
        await super().async_will_remove_from_hass()
