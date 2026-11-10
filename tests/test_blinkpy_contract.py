"""The installed blinkpy still provides what the native relay builds on."""

import importlib.util
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest

try:
    from blinkpy.camera import BlinkCamera
    from blinkpy.livestream import BlinkLiveStream
except ImportError:  # The protocol tests also run without blinkpy installed.
    BlinkLiveStream = None

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "blink_plus"
spec = importlib.util.spec_from_file_location("transport", ROOT / "transport.py")
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


@unittest.skipIf(BlinkLiveStream is None, "blinkpy is not installed")
class BlinkpyContractTests(unittest.TestCase):
    def test_live_stream_has_what_the_relay_uses(self):
        stream = BlinkLiveStream(
            SimpleNamespace(serial="TEST"),
            {
                "command_id": 1,
                "polling_interval": 1,
                "server": "immis://example.invalid:443/abc__def?client_id=1",
            },
        )
        for name in transport.REQUIRED:
            self.assertTrue(hasattr(stream, name), name)
        self.assertEqual(stream.clients, [])
        for name in ("feed", "recv"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(stream, name)), name)

    def test_feed_reads_through_the_replaceable_recv(self):
        # The relay swaps in its own recv on one stream object.
        self.assertIn("self.recv()", inspect.getsource(BlinkLiveStream.feed))

    def test_camera_can_open_a_live_stream(self):
        self.assertTrue(inspect.iscoroutinefunction(BlinkCamera.init_livestream))
