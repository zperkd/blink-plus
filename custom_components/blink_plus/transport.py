"""On-demand native Blink transport. No Home Assistant imports or global patches."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import time
from types import MethodType

_LOGGER = logging.getLogger(__name__)
MAX_PAYLOAD = 8 * 1024 * 1024


async def recv_packets(stream):
    """Read complete IMMI packets, forwarding native MPEG-TS and accessory state."""
    try:
        while True:
            header = await stream.target_reader.readexactly(9)
            length = int.from_bytes(header[5:9], "big")
            if length > MAX_PAYLOAD:
                raise ValueError("Oversized Blink packet")
            if not length:
                continue
            payload = await stream.target_reader.readexactly(length)
            kind = header[0]
            if kind == 0x15 and len(payload) >= 7:
                ident = int.from_bytes(header[1:5], "big")
                if ident in (2, 3):
                    position = {
                        "pan": int.from_bytes(payload[4:5], "big", signed=True),
                        "tilt": int.from_bytes(payload[5:6], "big", signed=True),
                    }
                    setattr(
                        stream, "position" if ident == 2 else "home_position", position
                    )
                    if ident == 2:
                        stream.position_version = (
                            getattr(stream, "position_version", 0) + 1
                        )
                        stream.mount_moving = payload[6] == 0x10
            if kind != 0 or payload[0] != 0x47:
                continue
            for writer in tuple(stream.clients):
                if writer.is_closing():
                    continue
                try:
                    writer.write(payload)
                    await asyncio.wait_for(writer.drain(), 2)
                except (OSError, TimeoutError):
                    writer.close()
    except asyncio.IncompleteReadError:
        pass
    finally:
        if stream.target_writer:
            stream.target_writer.close()


class NativeRelay:
    """A stable loopback source that only wakes a camera when a player connects."""

    def __init__(self, camera, duration=120, cooldown=30, on_auth_error=None):
        self.camera = camera
        self.duration = duration
        self.cooldown = cooldown
        self.on_auth_error = on_auth_error
        self.server = None
        self.stream = None
        self.runner = None
        self.clients = set()
        self.handlers = set()
        self.lock = asyncio.Lock()
        self.retry_after = 0.0
        self.closed = False
        self.starts = 0
        self.last_error = None

    async def source(self):
        """Create a local listener without contacting Blink."""
        async with self.lock:
            if self.closed:
                raise RuntimeError("Relay unloaded")
            if self.server is None:
                self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
            return f"tcp://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        try:
            async with self.lock:
                if self.closed or time.monotonic() < self.retry_after:
                    return
                self.clients.add(writer)
                if self.runner is None:
                    self.runner = asyncio.create_task(self._run())
                elif self.stream is not None:
                    self.stream.clients.append(writer)
            await (
                reader.read()
            )  # HA closes its input connection when its stream worker stops.
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            async with self.lock:
                self.clients.discard(writer)
                if self.stream and writer in self.stream.clients:
                    self.stream.clients.remove(writer)
                if not self.clients and self.runner:
                    self.runner.cancel()
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()
            self.handlers.discard(task)

    async def _run(self):
        upstream = None
        feed = None
        cooldown = self.cooldown
        try:
            try:
                async with asyncio.timeout(20):
                    upstream = await self.camera.init_livestream()
                    upstream.recv = MethodType(recv_packets, upstream)
                    # Reuse blinkpy's protocol/auth/keepalive, but not its TCP listener.
                    async with self.lock:
                        if not self.clients or self.closed:
                            return
                        self.stream = upstream
                        upstream.clients = list(self.clients)
                    self.starts += 1
                    self.last_error = None
                    feed = asyncio.create_task(upstream.feed())
            except TimeoutError:
                self.last_error = "start_timeout"
                _LOGGER.warning("Blink live session did not start in time")
                return
            await asyncio.wait_for(asyncio.shield(feed), self.duration)
        except asyncio.CancelledError:
            # The last viewer left normally; allow an immediate reopen.
            cooldown = 0
            raise
        except TimeoutError:
            self.last_error = "session_limit"
        except Exception as err:
            # Never log protocol URLs, tokens, credentials, or exception text.
            self.last_error = type(err).__name__
            _LOGGER.warning("Blink live session ended (%s)", self.last_error)
            if self.on_auth_error:
                self.on_auth_error(err)
        finally:
            if upstream:
                upstream.stop()
            if feed:
                feed.cancel()
                with suppress(asyncio.CancelledError, TimeoutError, Exception):
                    await asyncio.wait_for(feed, 5)
            if upstream and upstream.target_writer:
                try:
                    await asyncio.wait_for(upstream.target_writer.wait_closed(), 2)
                except (OSError, TimeoutError):
                    upstream.target_writer.transport.abort()
            async with self.lock:
                for writer in tuple(self.clients):
                    writer.close()
                self.stream = None
                self.runner = None
                self.retry_after = time.monotonic() + cooldown

    async def pan_tilt(
        self, action, pan_step=15, tilt_step=10, invert_pan=True, invert_tilt=False
    ):
        """Send accessory commands only through an already open live connection."""
        stream = self.stream
        if (
            stream is None
            or stream.target_writer is None
            or stream.target_writer.is_closing()
        ):
            raise RuntimeError("Open live view before moving the mount")
        if action == "home":
            identifier, payload = 5, b""
        else:
            if action not in {"left", "right", "up", "down"}:
                raise ValueError("Unknown pan/tilt direction")
            position = getattr(stream, "position", None)
            if position is None:
                raise RuntimeError("Waiting for the mount position")
            pan, tilt = position["pan"], position["tilt"]
            if action in {"left", "right"}:
                pan += (
                    pan_step
                    * (1 if action == "right" else -1)
                    * (-1 if invert_pan else 1)
                )
            else:
                tilt += (
                    tilt_step
                    * (1 if action == "up" else -1)
                    * (-1 if invert_tilt else 1)
                )
            pan, tilt = max(-128, min(127, pan)), max(-128, min(127, tilt))
            identifier = 3
            stream.position = {"pan": pan, "tilt": tilt}
            payload = (
                b"\0\0\0\0"
                + pan.to_bytes(1, "big", signed=True)
                + tilt.to_bytes(1, "big", signed=True)
                + b"\0"
            )
        packet = (
            b"\x14"
            + identifier.to_bytes(4, "big")
            + len(payload).to_bytes(4, "big")
            + payload
        )
        stream.target_writer.write(packet)
        await stream.target_writer.drain()

    async def close(self):
        """Stop accepting clients and await all owned tasks on unload."""
        self.closed = True
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.runner:
            runner = self.runner
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
        for writer in tuple(self.clients):
            writer.close()
        tasks = list(self.handlers)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
