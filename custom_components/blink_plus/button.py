"""Snapshot, recording and opt-in accessory pan/tilt controls."""

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from .entity import BlinkEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for camera in coordinator.api.cameras.values():
        entities.extend(
            [
                BlinkButton(coordinator, camera, "snapshot", "Take snapshot"),
                BlinkButton(coordinator, camera, "record", "Record local clip"),
            ]
        )
        if str(camera.serial) in coordinator.options["pan_tilt_cameras"]:
            entities.extend(
                BlinkButton(coordinator, camera, action, f"Pan/tilt {action}")
                for action in ("left", "right", "up", "down", "home")
            )
    async_add_entities(entities)


class BlinkButton(BlinkEntity, ButtonEntity):
    def __init__(self, coordinator, camera, action, name):
        super().__init__(coordinator, camera, action, name)
        self.action = action

    async def async_press(self):
        if self.action == "snapshot":
            await self.coordinator.snapshot(self.camera)
        elif self.action == "record":
            await self.coordinator.record_local(self.camera)
        else:
            o = self.coordinator.options
            try:
                await self.coordinator.relay(self.camera).pan_tilt(
                    self.action,
                    o["pan_step"],
                    o["tilt_step"],
                    o["invert_pan"],
                    o["invert_tilt"],
                )
            except (RuntimeError, ValueError, OSError) as err:
                raise HomeAssistantError(str(err)) from None
