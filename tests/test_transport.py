"""Protocol and data tests; run with python -m unittest discover -s tests -v."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "blink_plus"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transport = load("transport")
values = load("values")


class Writer:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed

    async def wait_closed(self):
        pass


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_headers_and_payloads(self):
        reader = asyncio.StreamReader()
        writer = Writer()
        target = Writer()
        stream = SimpleNamespace(
            target_reader=reader, target_writer=target, clients=[writer]
        )
        payload = b"\x47" + b"x" * 187
        packet = b"\0" * 5 + len(payload).to_bytes(4, "big") + payload
        task = asyncio.create_task(transport.recv_packets(stream))
        for byte in packet:
            reader.feed_data(bytes([byte]))
            await asyncio.sleep(0)
        reader.feed_eof()
        await task
        self.assertEqual(writer.data, payload)
        self.assertTrue(target.closed)

    async def test_truncated_packet_is_not_forwarded(self):
        reader = asyncio.StreamReader()
        writer = Writer()
        target = Writer()
        reader.feed_data(b"\0" * 5 + (188).to_bytes(4, "big") + b"\x47")
        reader.feed_eof()
        await transport.recv_packets(
            SimpleNamespace(
                target_reader=reader, target_writer=target, clients=[writer]
            )
        )
        self.assertFalse(writer.data)
        self.assertTrue(target.closed)

    async def test_oversized_packet_rejected(self):
        reader = asyncio.StreamReader()
        target = Writer()
        reader.feed_data(b"\0" * 5 + (transport.MAX_PAYLOAD + 1).to_bytes(4, "big"))
        with self.assertRaises(ValueError):
            await transport.recv_packets(
                SimpleNamespace(target_reader=reader, target_writer=target, clients=[])
            )
        self.assertTrue(target.closed)

    async def test_accessory_is_not_video(self):
        reader = asyncio.StreamReader()
        writer = Writer()
        target = Writer()
        payload = b"\0" * 4 + bytes([99, 246, 0])
        reader.feed_data(
            b"\x15" + (2).to_bytes(4, "big") + len(payload).to_bytes(4, "big") + payload
        )
        reader.feed_eof()
        stream = SimpleNamespace(
            target_reader=reader, target_writer=target, clients=[writer]
        )
        await transport.recv_packets(stream)
        self.assertEqual(stream.position, {"pan": 99, "tilt": -10})
        self.assertFalse(writer.data)

    async def test_source_does_not_wake_camera_and_is_stable(self):
        relay = transport.NativeRelay(SimpleNamespace())
        try:
            source = await relay.source()
            self.assertEqual(source, await relay.source())
            self.assertIn("127.0.0.1", source)
            self.assertEqual(relay.starts, 0)
        finally:
            await relay.close()
        self.assertFalse(relay.handlers)
        with self.assertRaises(RuntimeError):
            await relay.source()

    async def test_startup_failure_closes_client(self):
        class Camera:
            async def init_livestream(self):
                raise OSError("secret must not reach logs")

        relay = transport.NativeRelay(Camera(), cooldown=1)
        try:
            port = int((await relay.source()).rsplit(":", 1)[1])
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
            writer.close()
            await writer.wait_closed()
            self.assertEqual(relay.last_error, "OSError")
            self.assertEqual(relay.starts, 0)
        finally:
            await relay.close()

    async def test_incompatible_blinkpy_is_reported(self):
        class Camera:
            async def init_livestream(self):
                return SimpleNamespace(feed=None, stop=None)

        relay = transport.NativeRelay(Camera(), cooldown=1)
        try:
            port = int((await relay.source()).rsplit(":", 1)[1])
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
            writer.close()
            await writer.wait_closed()
            self.assertEqual(relay.last_error, "incompatible_blinkpy")
            self.assertEqual(relay.starts, 0)
        finally:
            await relay.close()

    async def test_pan_tilt_requires_active_session(self):
        relay = transport.NativeRelay(SimpleNamespace())
        with self.assertRaises(RuntimeError):
            await relay.pan_tilt("right")

    async def test_pan_tilt_packet_signed_and_inverted(self):
        relay = transport.NativeRelay(SimpleNamespace())
        writer = Writer()
        relay.stream = SimpleNamespace(
            target_writer=writer, position={"pan": 84, "tilt": -100}
        )
        await relay.pan_tilt("right")
        self.assertEqual(writer.data[:5], b"\x14\0\0\0\x03")
        self.assertEqual(writer.data[13], 69)
        self.assertEqual(writer.data[14], 156)

    async def test_two_viewers_share_one_session_and_reopen(self):
        class Stream:
            target_reader = None
            target_writer = None

            async def recv(self):
                pass

            def __init__(self):
                self.clients = []

            async def feed(self):
                while True:
                    for writer in tuple(self.clients):
                        writer.write(b"\x47" + b"x" * 187)
                        await writer.drain()
                    await asyncio.sleep(0.01)

            def stop(self):
                for writer in tuple(self.clients):
                    writer.close()

        class Camera:
            def __init__(self):
                self.calls = 0

            async def init_livestream(self):
                self.calls += 1
                return Stream()

        camera = Camera()
        relay = transport.NativeRelay(camera, cooldown=5)
        writers = []
        try:
            port = int((await relay.source()).rsplit(":", 1)[1])
            r1, w1 = await asyncio.open_connection("127.0.0.1", port)
            writers.append(w1)
            r2, w2 = await asyncio.open_connection("127.0.0.1", port)
            writers.append(w2)
            self.assertTrue(await asyncio.wait_for(r1.read(188), 1))
            self.assertTrue(await asyncio.wait_for(r2.read(188), 1))
            self.assertEqual(camera.calls, 1)
            w1.close()
            await w1.wait_closed()
            await asyncio.sleep(0.03)
            self.assertIsNotNone(relay.runner)
            w2.close()
            await w2.wait_closed()
            for _ in range(30):
                if relay.runner is None:
                    break
                await asyncio.sleep(0.01)
            self.assertIsNone(relay.runner)
            # A normal close does not start the cooldown: reopening works at once.
            r3, w3 = await asyncio.open_connection("127.0.0.1", port)
            writers.append(w3)
            self.assertTrue(await asyncio.wait_for(r3.read(188), 1))
            self.assertEqual(camera.calls, 2)
        finally:
            for writer in writers:
                writer.close()
            await relay.close()
        self.assertFalse(relay.handlers)

    async def test_session_duration_closes_viewer(self):
        class Stream:
            target_reader = None
            target_writer = None

            async def recv(self):
                pass

            def __init__(self):
                self.clients = []

            async def feed(self):
                await asyncio.sleep(10)

            def stop(self):
                for writer in self.clients:
                    writer.close()

        class Camera:
            calls = 0

            async def init_livestream(self):
                self.calls += 1
                return Stream()

        camera = Camera()
        relay = transport.NativeRelay(camera, duration=0.03, cooldown=5)
        try:
            port = int((await relay.source()).rsplit(":", 1)[1])
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
            self.assertEqual(relay.last_error, "session_limit")
            writer.close()
            await writer.wait_closed()
            for _ in range(30):
                if relay.runner is None:
                    break
                await asyncio.sleep(0.01)
            # The time limit starts the cooldown: a reconnect is refused.
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
            writer.close()
            await writer.wait_closed()
            self.assertEqual(camera.calls, 1)
        finally:
            await relay.close()


class ValueTests(unittest.TestCase):
    def test_voltage_is_hundredths(self):
        self.assertEqual(
            values.sensor_value(
                SimpleNamespace(battery_voltage=173), "battery_voltage"
            ),
            1.73,
        )

    def test_no_invented_voltage(self):
        self.assertIsNone(values.sensor_value(SimpleNamespace(), "battery_voltage"))

    def test_calibrated_temperature(self):
        self.assertEqual(
            values.sensor_value(
                SimpleNamespace(temperature=80, temperature_calibrated=82),
                "temperature",
            ),
            82,
        )

    def test_temperature_zero_is_valid(self):
        self.assertEqual(
            values.sensor_value(
                SimpleNamespace(temperature=0, temperature_calibrated=0), "temperature"
            ),
            0,
        )

    def test_battery_bars_stay_bars(self):
        self.assertEqual(
            values.sensor_value(SimpleNamespace(battery_level=3), "battery_level"), 3
        )

    def test_missing_battery_is_not_ok(self):
        self.assertIsNone(values.binary_value(SimpleNamespace(), "battery_low"))

    def test_low_battery(self):
        self.assertTrue(
            values.binary_value(SimpleNamespace(battery="low"), "battery_low")
        )
        self.assertFalse(
            values.binary_value(SimpleNamespace(battery="ok"), "battery_low")
        )

    def test_motion_false_is_supported(self):
        self.assertIs(
            values.binary_value(
                SimpleNamespace(motion_detected=False), "motion_detected"
            ),
            False,
        )

    def test_bad_timestamp_not_reported(self):
        self.assertIsNone(
            values.sensor_value(SimpleNamespace(last_record="unknown"), "last_record")
        )

    def test_timestamp_timezone(self):
        self.assertIsNotNone(
            values.sensor_value(
                SimpleNamespace(last_record="2026-11-10T12:00:00Z"), "last_record"
            ).tzinfo
        )


if __name__ == "__main__":
    unittest.main()
