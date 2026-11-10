"""Blink Plus constants."""

DOMAIN = "blink_plus"
PLATFORMS = ["camera", "sensor", "binary_sensor", "switch", "button"]
DEFAULTS = {
    "scan_interval": 300,
    "cloud_enabled": True,
    "cloud_history_days": 30,
    "cloud_max_clips": 1000,
    "cloud_refresh_seconds": 60,
    "cloud_cache_mb": 128,
    "recording_seconds": 30,
    "recording_directory": "",
    "live_enabled": True,
    "max_live_seconds": 120,
    "reconnect_cooldown": 30,
    "pan_tilt_cameras": [],
    "pan_step": 15,
    "tilt_step": 10,
    "invert_pan": True,
    "invert_tilt": False,
}
