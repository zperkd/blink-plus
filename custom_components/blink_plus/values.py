"""Capability-aware sensor conversion, independent of Home Assistant."""

from datetime import datetime, timezone


def sensor_value(camera, key):
    value = getattr(camera, key, None)
    if key == "temperature":
        calibrated = getattr(camera, "temperature_calibrated", None)
        return calibrated if calibrated is not None else value
    if key == "battery_voltage":
        return value / 100 if isinstance(value, (int, float)) else None
    if key == "last_record":
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return None
    return value


def binary_value(camera, key):
    if key == "battery_low":
        state = getattr(camera, "battery", None)
        if state not in {"ok", "low"}:
            return None
        return state == "low"
    if key == "online":
        if getattr(camera, "status", None) is None:
            return None
        return camera.online
    return getattr(camera, key, None)
