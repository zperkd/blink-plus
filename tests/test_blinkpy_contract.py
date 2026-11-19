"""The installed blinkpy still provides what the native relay builds on."""

import importlib.util
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

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

    def test_load_reductions_find_what_they_replace(self):
        # blinkpy_patches.py replaces these; refresh must still go through them.
        from blinkpy.sync_module import BlinkSyncModule, LocalStorageMediaItem

        for cls, name in (
            (LocalStorageMediaItem, "prepare_download"),
            (BlinkSyncModule, "update_local_storage_manifest"),
            (BlinkSyncModule, "get_network_info"),
            (BlinkCamera, "get_sensor_info"),
        ):
            self.assertTrue(inspect.iscoroutinefunction(getattr(cls, name)), name)
        refresh = inspect.getsource(BlinkSyncModule.refresh)
        self.assertIn("self.get_network_info()", refresh)
        self.assertIn("self.update_local_storage_manifest()", refresh)
        self.assertIn(
            "prepare_download(", inspect.getsource(BlinkSyncModule.check_new_videos)
        )

    def test_own_token_refresh_has_what_it_uses(self):
        # coordinator.py refreshes tokens itself and then finishes Blink.start().
        from blinkpy.auth import Auth
        from blinkpy.blinkpy import Blink, BlinkSetupError
        from blinkpy.helpers import constants

        for name in (
            "OAUTH_SCOPE",
            "OAUTH_TOKEN_URL",
            "OAUTH_TOKEN_USER_AGENT",
            "OAUTH_V2_CLIENT_ID",
        ):
            self.assertIsInstance(getattr(constants, name, None), str, name)
        self.assertTrue(issubclass(BlinkSetupError, Exception))
        self.assertTrue(callable(Blink.setup_urls))
        for name in ("get_homescreen", "setup_post_verify", "refresh", "start"):
            self.assertTrue(inspect.iscoroutinefunction(getattr(Blink, name)), name)
        start = inspect.getsource(Blink.start)
        for step in ("auth.startup()", "setup_urls()", "get_homescreen()"):
            self.assertIn(step, start)
        self.assertIn("setup_post_verify()", start)
        attributes = inspect.getsource(Auth)
        for name in ("refresh_token", "hardware_id", "expiration_date", "expires_in"):
            self.assertIn(f"self.{name}", attributes)


@unittest.skipIf(BlinkLiveStream is None, "blinkpy is not installed")
class LiveTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_token_populates_only_its_handshake_field(self):
        camera = SimpleNamespace(
            serial="TEST",
            sync=SimpleNamespace(blink=object(), network_id=1),
            camera_id=2,
            camera_type="owl",
        )
        response = {
            "command_id": 1,
            "polling_interval": 1,
            "server": "immis://example.invalid:443/abc__def?client_id=1",
            "liveview_token": "test-session-token",
        }
        original = BlinkLiveStream(camera, response).get_auth_header()
        with patch(
            "blinkpy.api.request_camera_liveview", new_callable=AsyncMock
        ) as request:
            request.return_value = response
            stream = await transport.init_livestream(camera)
        header = stream.get_auth_header()
        self.assertEqual(header[:34], original[:34])
        self.assertEqual(header[34:98], b"test-session-token".ljust(64, b"\x00"))
        self.assertEqual(header[98:122], original[98:])
        self.assertEqual(header[122:], b"\x0a" + bytes(8))
        self.assertEqual(len(header), 131)
        # Older responses without a token retain working receive-only video.
        response.pop("liveview_token")
        with patch(
            "blinkpy.api.request_camera_liveview", new_callable=AsyncMock
        ) as request:
            request.return_value = response
            stream = await transport.init_livestream(camera)
        self.assertEqual(stream.get_auth_header(), original)

    async def test_invalid_tokens_do_not_shift_handshake_fields(self):
        camera = SimpleNamespace(
            serial="TEST",
            sync=SimpleNamespace(blink=object(), network_id=1),
            camera_id=2,
            camera_type="owl",
        )
        for token in ("x" * 65, 123):
            with self.subTest(token_type=type(token).__name__):
                response = {
                    "command_id": 1,
                    "polling_interval": 1,
                    "server": "immis://example.invalid:443/abc__def?client_id=1",
                    "liveview_token": token,
                }
                with patch(
                    "blinkpy.api.request_camera_liveview", new_callable=AsyncMock
                ) as request:
                    request.return_value = response
                    with self.assertRaisesRegex(ValueError, "Invalid Blink"):
                        await transport.init_livestream(camera)
