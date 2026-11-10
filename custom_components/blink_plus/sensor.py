"""Only expose real readings reported by each camera model."""

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfTemperature,
    UnitOfElectricPotential,
)
from .entity import BlinkEntity
from .values import sensor_value

SENSORS = {
    "temperature": (
        "Temperature",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.FAHRENHEIT,
    ),
    "battery_voltage": (
        "Battery voltage",
        SensorDeviceClass.VOLTAGE,
        UnitOfElectricPotential.VOLT,
    ),
    "battery_level": ("Battery level (Blink bars)", None, None),
    "wifi_strength": ("Wi-Fi signal", SensorDeviceClass.SIGNAL_STRENGTH, "dBm"),
    "sync_signal_strength": ("Sync signal (Blink bars)", None, None),
    "last_record": ("Last recording", SensorDeviceClass.TIMESTAMP, None),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known = set()

    def discover():
        entities = []
        for camera in coordinator.api.cameras.values():
            for key in SENSORS:
                identity = (camera.serial, key)
                if identity not in known and sensor_value(camera, key) is not None:
                    known.add(identity)
                    entities.append(BlinkSensor(coordinator, camera, key))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class BlinkSensor(BlinkEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, camera, key):
        name, device_class, unit = SENSORS[key]
        super().__init__(coordinator, camera, key, name)
        self.key = key
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        if device_class and device_class != SensorDeviceClass.TIMESTAMP:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return sensor_value(self.camera, self.key)
