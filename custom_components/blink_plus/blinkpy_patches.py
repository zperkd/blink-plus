"""Keep Blink Plus's own polling away from the Sync Module.

On every refresh blinkpy does work that keeps a Sync Module busy, and the Blink
app then answers "system busy" and live view fails:

* it asks a Sync Module 2 with a USB drive for its clip list (the module scans
  the drive),
* it makes the module upload every new USB clip to the cloud.

It also makes two requests whose answer the refresh already has or rarely needs:

* the network state, although the homescreen that the same refresh has just
  loaded already lists it,
* every outdoor camera's signals, only to read a calibrated temperature.

Blink Plus replaces these four blinkpy methods. The replacements only act for
Blink Plus's own Blink instance, which carries ``blink_plus_usb_clip_minutes``.
The built-in Blink integration uses the same blinkpy classes and keeps the
original behaviour.

blinkpy ships with Home Assistant, and its internals can change with any update.
Every replacement is therefore optional: if a class or method is gone, Blink Plus
logs it once and leaves blinkpy's behaviour as it is (more load, nothing breaks).
"""

from __future__ import annotations

from collections.abc import Callable
import importlib
import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Calibrated temperature changes slowly; one signals request per camera per hour
# keeps the sensor useful without asking the camera on every poll.
SIGNALS_SECONDS = 3600

_APPLIED: dict[str, bool] | None = None


def _ours(blink: Any) -> bool:
    """True for Blink Plus's own Blink instance."""
    return getattr(blink, "blink_plus_usb_clip_minutes", None) is not None


def _wrap(module: str, cls_name: str, method: str, make: Callable[[Any], Any]) -> bool:
    """Replace cls.method with make(original). False (and a warning) if impossible."""
    try:
        cls = getattr(importlib.import_module(module), cls_name)
        original = getattr(cls, method)
    except (ImportError, AttributeError):
        _LOGGER.warning(
            "blinkpy has no %s.%s.%s (changed in a Home Assistant update?). "
            "Blink Plus keeps working without this load reduction",
            module,
            cls_name,
            method,
        )
        return False
    if not callable(original):
        _LOGGER.warning("blinkpy %s.%s is not callable, not replaced", cls_name, method)
        return False
    setattr(cls, method, make(original))
    return True


def _patch_prepare_download(original):
    """Don't make the Sync Module upload every new USB clip to the cloud."""

    async def prepare_download(self, blink, *args, **kwargs):
        if _ours(blink):
            return None
        return await original(self, blink, *args, **kwargs)

    return prepare_download


def _patch_manifest(original):
    """Read the USB clip list at most every N minutes, never with N = 0."""

    async def update_local_storage_manifest(self, *args, **kwargs):
        blink = getattr(self, "blink", None)
        if not _ours(blink):
            return await original(self, *args, **kwargs)
        minutes = blink.blink_plus_usb_clip_minutes
        now = time.monotonic()
        last = getattr(self, "_blink_plus_last_manifest", None)
        if minutes <= 0 or (last is not None and now - last < minutes * 60):
            try:
                self._local_storage["manifest_stale"] = True
            except (AttributeError, KeyError, TypeError):
                pass  # blinkpy changed its internals: just skip the flag
            return None
        self._blink_plus_last_manifest = now
        return await original(self, *args, **kwargs)

    return update_local_storage_manifest


def _patch_network_info(original):
    """Take armed/online from the homescreen instead of a Sync Module request."""

    async def get_network_info(self, *args, **kwargs):
        blink = getattr(self, "blink", None)
        if not _ours(blink):
            return await original(self, *args, **kwargs)
        networks = (getattr(blink, "homescreen", None) or {}).get("networks") or []
        for net in networks:
            if isinstance(net, dict) and str(net.get("id")) == str(
                getattr(self, "network_id", None)
            ):
                self.network_info = {
                    "network": {
                        "id": net.get("id"),
                        "name": net.get("name"),
                        "armed": net.get("armed"),
                        "sync_module_error": False,
                    }
                }
                return True
        # Not in the homescreen: ask the module as blinkpy would.
        return await original(self, *args, **kwargs)

    return get_network_info


def _patch_sensor_info(original):
    """Ask a camera for its signals at most once an hour."""

    async def get_sensor_info(self, *args, **kwargs):
        blink = getattr(getattr(self, "sync", None), "blink", None)
        if not _ours(blink):
            return await original(self, *args, **kwargs)
        now = time.monotonic()
        last = getattr(self, "_blink_plus_last_signals", None)
        if last is not None and now - last < SIGNALS_SECONDS:
            if getattr(self, "temperature_calibrated", None) is None:
                self.temperature_calibrated = getattr(self, "temperature", None)
            return None
        self._blink_plus_last_signals = now
        return await original(self, *args, **kwargs)

    return get_sensor_info


def apply_blinkpy_patches() -> dict[str, bool]:
    """Apply all load reductions once. Returns which ones are active."""
    global _APPLIED  # noqa: PLW0603
    if _APPLIED is not None:
        return _APPLIED
    _APPLIED = {
        "prepare_download": _wrap(
            "blinkpy.sync_module",
            "LocalStorageMediaItem",
            "prepare_download",
            _patch_prepare_download,
        ),
        "local_storage_manifest": _wrap(
            "blinkpy.sync_module",
            "BlinkSyncModule",
            "update_local_storage_manifest",
            _patch_manifest,
        ),
        "network_info": _wrap(
            "blinkpy.sync_module",
            "BlinkSyncModule",
            "get_network_info",
            _patch_network_info,
        ),
        "sensor_info": _wrap(
            "blinkpy.camera", "BlinkCamera", "get_sensor_info", _patch_sensor_info
        ),
    }
    return _APPLIED
