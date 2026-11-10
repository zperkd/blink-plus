"""Motion, low battery and connectivity where reported."""

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from .entity import BlinkEntity
from .values import binary_value

TYPES = {
    "motion_detected": ("Motion", BinarySensorDeviceClass.MOTION),
    "battery_low": ("Battery", BinarySensorDeviceClass.BATTERY),
    "online": ("Connectivity", BinarySensorDeviceClass.CONNECTIVITY),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known = set()

    def discover():
        entities = []
        for camera in coordinator.api.cameras.values():
            for key in TYPES:
                identity = (camera.serial, key)
                if identity not in known and binary_value(camera, key) is not None:
                    known.add(identity)
                    entities.append(BlinkBinarySensor(coordinator, camera, key))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class BlinkBinarySensor(BlinkEntity, BinarySensorEntity):
    def __init__(self, coordinator, camera, key):
        name, device_class = TYPES[key]
        super().__init__(coordinator, camera, key, name)
        self.key = key
        self._attr_device_class = device_class

    @property
    def is_on(self):
        return binary_value(self.camera, self.key)
