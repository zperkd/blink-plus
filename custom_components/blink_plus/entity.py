"""Shared entity identity and availability."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


class BlinkEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, camera, key, name):
        super().__init__(coordinator)
        self.camera = camera
        self._attr_unique_id = f"{camera.serial}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(camera.serial))},
            name=camera.name,
            manufacturer="Blink",
            model=camera.product_type or camera.camera_type,
            serial_number=camera.serial,
            sw_version=camera.version,
        )
