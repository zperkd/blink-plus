"""Native HA microphone sessions, with in-memory PCM-to-AAC encoding."""

import asyncio
import base64
import binascii
from contextlib import suppress
from fractions import Fraction
import secrets

import av
import probatio as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components import websocket_api
from homeassistant.core import callback

from .live_http import find_relay

DATA_KEY = "blink_plus_microphones"


class AACEncoder:
    """Encode 16 kHz mono PCM into the ADTS frames the camera accepts."""

    def __init__(self):
        self.codec = av.CodecContext.create("aac", "w")
        self.codec.sample_rate = 16000
        self.codec.layout = "mono"
        self.codec.format = "fltp"
        self.codec.bit_rate = 24000
        self.codec.time_base = Fraction(1, 16000)
        self.codec.open()
        self.resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
        self.samples = 0

    @staticmethod
    def _adts(packet):
        payload = bytes(packet)
        length = len(payload) + 7
        if length > 8191:
            raise ValueError("Oversized encoded audio")
        header = bytes(
            (
                0xFF,
                0xF1,
                0x60,
                0x40 | (length >> 11),
                (length >> 3) & 0xFF,
                ((length & 7) << 5) | 0x1F,
                0xFC,
            )
        )
        return header + payload

    def encode(self, pcm):
        frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
        frame.planes[0].update(pcm.ljust(frame.planes[0].buffer_size, b"\0"))
        frame.sample_rate = 16000
        frame.time_base = Fraction(1, 16000)
        frame.pts = self.samples
        self.samples += frame.samples
        return [
            self._adts(packet)
            for converted in self.resampler.resample(frame)
            for packet in self.codec.encode(converted)
        ]

    def finish(self):
        packets = [
            self._adts(packet)
            for frame in self.resampler.resample(None)
            for packet in self.codec.encode(frame)
        ]
        return packets + [self._adts(packet) for packet in self.codec.encode(None)]


class MicrophoneSession:
    def __init__(self, hass, connection, message_id, relay, entity_id):
        self.hass = hass
        self.connection = connection
        self.message_id = message_id
        self.entity_id = entity_id
        self.relay = relay
        self.stream = relay.stream
        self.ident = secrets.token_urlsafe(24)
        self.queue = asyncio.Queue(maxsize=4)
        self.sequence = 0
        self.encoder = None
        self.task = None
        self.stopping = False
        self.cleaned = False
        self.clock = None
        self.speaker_started = False

    async def start(self):
        try:
            self.encoder = await self.hass.async_add_executor_job(AACEncoder)
            self.speaker_started = True
            await self.relay.start_talk()
            if self.stopping or self.relay.stream is not self.stream:
                raise RuntimeError("Live view ended")
            self.task = self.hass.async_create_background_task(
                self.run(), "Blink Plus microphone"
            )
            self.relay.talk_worker = self.task
        except BaseException:
            await self.cleanup()
            raise

    def stop(self):
        """Cancel on a dropped websocket or integration shutdown."""
        if self.stopping:
            return
        self.stopping = True
        if self.task is not None and not self.task.done():
            self.task.cancel()

    async def finish(self):
        """Drain the last bounded packets and close the speaker."""
        if self.task is None:
            self.stop()
            return
        self.stopping = True
        # A full queue will be drained before the worker checks stopping again.
        if not self.queue.full():
            self.queue.put_nowait(None)
        await asyncio.gather(self.task, return_exceptions=True)

    async def send(self, frames):
        loop = asyncio.get_running_loop()
        for frame in frames:
            now = loop.time()
            if self.clock is None or self.clock < now - 0.5:
                self.clock = now
            await asyncio.sleep(max(0, self.clock - now))
            if self.relay.stream is not self.stream:
                raise RuntimeError("Live view ended")
            await self.relay.send_audio(frame)
            self.clock += 0.064

    async def run(self):
        try:
            async with asyncio.timeout(60):
                while not (self.stopping and self.queue.empty()):
                    pcm = await asyncio.wait_for(self.queue.get(), 5)
                    if pcm is None:
                        break
                    frames = await self.hass.async_add_executor_job(
                        self.encoder.encode, pcm
                    )
                    await self.send(frames)
                frames = await self.hass.async_add_executor_job(self.encoder.finish)
                await self.send(frames)
        except (OSError, RuntimeError, TimeoutError, av.FFmpegError):
            pass
        finally:
            await self.cleanup()

    async def cleanup(self):
        if self.cleaned:
            return
        self.cleaned = True
        self.stopping = True
        self.hass.data[DATA_KEY].pop(self.ident, None)
        self.connection.subscriptions.pop(self.message_id, None)
        try:
            if self.speaker_started and self.relay.stream is self.stream:
                with suppress(Exception):
                    await self.relay.stop_talk()
        finally:
            self.encoder = None
            while not self.queue.empty():
                self.queue.get_nowait()
            if self.relay.talk_worker is self.task:
                self.relay.talk_worker = None
            self.relay.talk_lock.release()


def setup(hass):
    hass.data[DATA_KEY] = {}
    for command in (start, audio, stop):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "blink_plus/talk/start",
        vol.Required("entity_id"): str,
    }
)
@websocket_api.async_response
async def start(hass, connection, msg):
    entity_id = msg["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_CONTROL):
        connection.send_error(
            msg["id"], "unauthorized", "Camera control permission required"
        )
        return
    relay = find_relay(hass, entity_id)
    if relay is None or relay.stream is None:
        connection.send_error(msg["id"], "not_ready", "Open live video before talking")
        return
    if relay.talk_lock.locked():
        connection.send_error(
            msg["id"], "busy", "Someone is already talking to this camera"
        )
        return
    await relay.talk_lock.acquire()
    session = MicrophoneSession(hass, connection, msg["id"], relay, entity_id)
    hass.data[DATA_KEY][session.ident] = session
    connection.subscriptions[msg["id"]] = session.stop
    try:
        await session.start()
    except (OSError, RuntimeError, av.FFmpegError, ValueError):
        connection.send_error(msg["id"], "not_ready", "Camera could not start talk")
        return
    connection.send_result(msg["id"], {"session": session.ident, "max_seconds": 60})


def owned_session(hass, connection, msg):
    session = hass.data[DATA_KEY].get(msg["session"])
    if session is None or session.connection is not connection:
        connection.send_error(msg["id"], "not_found", "Talk session ended")
        return None
    if not connection.user.permissions.check_entity(session.entity_id, POLICY_CONTROL):
        session.stop()
        connection.send_error(
            msg["id"], "unauthorized", "Camera control permission required"
        )
        return None
    return session


@websocket_api.websocket_command(
    {
        vol.Required("type"): "blink_plus/talk/audio",
        vol.Required("session"): str,
        vol.Required("sequence"): vol.All(int, vol.Range(min=0)),
        vol.Required("samples"): vol.All(str, vol.Length(max=9000)),
    }
)
@callback
def audio(hass, connection, msg):
    session = owned_session(hass, connection, msg)
    if session is None:
        return
    try:
        pcm = base64.b64decode(msg["samples"], validate=True)
    except (ValueError, binascii.Error):
        connection.send_error(msg["id"], "invalid_audio", "Invalid microphone audio")
        return
    if not pcm or len(pcm) > 6400 or len(pcm) % 2:
        connection.send_error(
            msg["id"], "invalid_audio", "Invalid microphone packet size"
        )
        return
    if session.stopping or msg["sequence"] != session.sequence:
        connection.send_error(
            msg["id"], "not_ready", "Microphone packets arrived out of order"
        )
        return
    try:
        session.queue.put_nowait(pcm)
    except asyncio.QueueFull:
        session.stop()
        connection.send_error(msg["id"], "busy", "Connection is too slow for live talk")
        return
    session.sequence += 1
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "blink_plus/talk/stop",
        vol.Required("session"): str,
    }
)
@websocket_api.async_response
async def stop(hass, connection, msg):
    session = owned_session(hass, connection, msg)
    if session is None:
        return
    await session.finish()
    connection.send_result(msg["id"])
