"""Load reductions: active for Blink Plus's own Blink, untouched for anyone else,
and harmless when blinkpy's internals have changed."""

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "blink_plus"


def load_patches():
    spec = importlib.util.spec_from_file_location(
        "blink_plus_patches_under_test", ROOT / "blinkpy_patches.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_blinkpy(calls, full=True):
    """Stand-ins for the blinkpy classes, without touching sys.modules."""

    class LocalStorageMediaItem:
        async def prepare_download(self, blink, *args, **kwargs):
            calls.append("prepare_download")
            return "original"

    class BlinkSyncModule:
        def __init__(self, blink):
            self.blink = blink
            self.network_id = 7
            self._local_storage = {}

        async def update_local_storage_manifest(self, *args, **kwargs):
            calls.append("manifest")
            return "original"

        async def get_network_info(self, *args, **kwargs):
            calls.append("network_info")
            return "original"

    class BlinkCamera:
        def __init__(self, sync):
            self.sync = sync
            self.temperature = 21

        async def get_sensor_info(self, *args, **kwargs):
            calls.append("signals")
            self.temperature_calibrated = 20
            return "original"

    sync_module = ModuleType("blinkpy.sync_module")
    sync_module.LocalStorageMediaItem = LocalStorageMediaItem
    sync_module.BlinkSyncModule = BlinkSyncModule
    camera = ModuleType("blinkpy.camera")
    if full:
        camera.BlinkCamera = BlinkCamera
    else:  # a future blinkpy: one class renamed, one method gone
        del BlinkSyncModule.get_network_info
        camera.BlinkCameraV2 = BlinkCamera
    modules = {"blinkpy.sync_module": sync_module, "blinkpy.camera": camera}
    return modules, sync_module, BlinkCamera


class Ours:
    blink_plus_usb_clip_minutes = 60
    homescreen = {"networks": [{"id": 7, "name": "Home", "armed": True}]}


class BuiltIn:
    homescreen = {"networks": [{"id": 7, "name": "Home", "armed": True}]}


class BlinkpyPatchTests(unittest.TestCase):
    def apply(self, full=True):
        calls = []
        modules, sync_module, camera_cls = fake_blinkpy(calls, full)
        patches = load_patches()
        with patch.object(
            patches.importlib, "import_module", side_effect=modules.__getitem__
        ):
            applied = patches.apply_blinkpy_patches()
        return patches, applied, calls, sync_module, camera_cls

    def test_only_blink_plus_instances_are_spared(self):
        patches, applied, calls, sm, Camera = self.apply()
        self.assertTrue(all(applied.values()))
        self.assertIs(patches.apply_blinkpy_patches(), applied)  # once only

        async def run():
            ours, builtin = sm.BlinkSyncModule(Ours()), sm.BlinkSyncModule(BuiltIn())
            item = sm.LocalStorageMediaItem()
            self.assertIsNone(await item.prepare_download(Ours()))
            self.assertEqual(await item.prepare_download(BuiltIn()), "original")
            # First USB clip list read allowed, the next one within the hour skipped.
            self.assertEqual(await ours.update_local_storage_manifest(), "original")
            self.assertIsNone(await ours.update_local_storage_manifest())
            self.assertTrue(ours._local_storage["manifest_stale"])
            self.assertEqual(await builtin.update_local_storage_manifest(), "original")
            self.assertEqual(await builtin.update_local_storage_manifest(), "original")
            self.assertIs(await ours.get_network_info(), True)
            self.assertIs(ours.network_info["network"]["armed"], True)
            self.assertEqual(await builtin.get_network_info(), "original")
            cam_ours, cam_builtin = Camera(ours), Camera(builtin)
            # Signals once, then from memory for an hour.
            self.assertEqual(await cam_ours.get_sensor_info(), "original")
            self.assertIsNone(await cam_ours.get_sensor_info())
            self.assertEqual(cam_ours.temperature_calibrated, 20)
            self.assertEqual(await cam_builtin.get_sensor_info(), "original")
            self.assertEqual(await cam_builtin.get_sensor_info(), "original")

        asyncio.run(run())
        self.assertEqual(
            calls,
            [
                "prepare_download",
                "manifest",
                "manifest",
                "manifest",
                "network_info",
                "signals",
                "signals",
                "signals",
            ],
        )

    def test_zero_minutes_never_reads_the_usb_clip_list(self):
        _, _, calls, sm, _ = self.apply()

        class Never(Ours):
            blink_plus_usb_clip_minutes = 0

        async def run():
            sync = sm.BlinkSyncModule(Never())
            for _ in range(3):
                self.assertIsNone(await sync.update_local_storage_manifest())

        asyncio.run(run())
        self.assertEqual(calls, [])

    def test_unknown_network_falls_back_to_blinkpy(self):
        _, _, calls, sm, _ = self.apply()

        class Elsewhere(Ours):
            homescreen = {"networks": [{"id": 8}]}

        self.assertEqual(
            asyncio.run(sm.BlinkSyncModule(Elsewhere()).get_network_info()), "original"
        )
        self.assertEqual(calls, ["network_info"])

    def test_changed_internals_do_not_crash(self):
        _, _, _, sm, _ = self.apply()

        async def run():
            sync = sm.BlinkSyncModule(Ours())
            await sync.update_local_storage_manifest()
            sync._local_storage = None
            self.assertIsNone(await sync.update_local_storage_manifest())

        asyncio.run(run())

    def test_missing_parts_are_skipped_and_the_rest_applied(self):
        _, applied, _, sm, _ = self.apply(full=False)
        self.assertEqual(
            applied,
            {
                "prepare_download": True,
                "local_storage_manifest": True,
                "network_info": False,
                "sensor_info": False,
            },
        )
        self.assertIsNone(
            asyncio.run(sm.LocalStorageMediaItem().prepare_download(Ours()))
        )


if __name__ == "__main__":
    unittest.main()
