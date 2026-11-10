"""Camera motion detection and network arming."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .entity import BlinkEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [
        MotionSwitch(coordinator, c)
        for c in coordinator.api.cameras.values()
        if c.motion_enabled is not None
    ]
    entities += [NetworkSwitch(coordinator, s) for s in coordinator.api.sync.values()]
    async_add_entities(entities)


class MotionSwitch(BlinkEntity, SwitchEntity):
    def __init__(self, coordinator, camera):
        super().__init__(coordinator, camera, "motion_enabled", "Motion detection")

    @property
    def is_on(self):
        return self.camera.motion_enabled

    async def async_turn_on(self, **kwargs):
        await self.coordinator.command(self.camera.async_arm, True)
        self.camera.motion_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.coordinator.command(self.camera.async_arm, False)
        self.camera.motion_enabled = False
        self.async_write_ha_state()


class NetworkSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Armed"
    _attr_icon = "mdi:shield-home"

    def __init__(self, coordinator, sync):
        super().__init__(coordinator)
        self.sync = sync
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{sync.network_id}_armed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"network_{sync.network_id}")},
            manufacturer="Blink",
            name=sync.name,
            model="Blink network",
        )

    @property
    def is_on(self):
        return self.sync.arm

    async def async_turn_on(self, **kwargs):
        await self.coordinator.command(self.sync.async_arm, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.command(self.sync.async_arm, False)
