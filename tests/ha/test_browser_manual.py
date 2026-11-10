"""Explicit opt-in: real HA HLS playback driven by a browser through an SSH tunnel."""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from aiohttp import ClientSession, TCPConnector, ThreadedResolver, web
from aiohttp.test_utils import TestServer
from homeassistant.components.http import HomeAssistantView
from pytest_homeassistant.common import MockConfigEntry

pytestmark = pytest.mark.skipif(
    os.environ.get("BLINK_PLUS_BROWSER_TEST") != "1",
    reason="Explicit browser-test opt in required",
)

HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Blink Plus playback validation</title></head>
<body style="background:#111;color:#eee;font:16px sans-serif"><h1>Blink Plus playback validation</h1><p id="status">Starting</p>
<video id="video" controls autoplay muted playsinline style="width:90vw;max-height:80vh"></video><pre id="result"></pre>
<script src="/blink-plus-hls.js"></script><script>
const label=__LABEL__, source=__SOURCE__, video=document.getElementById('video');
const started=performance.now(); let first=null, last=null, gaps=[], count=0, stalls=0, finished=false;
const hls=new Hls({lowLatencyMode:true,backBufferLength:15});
const result={camera:label,errors:[]};
function finish(error){if(finished)return;finished=true;
 const q=video.getVideoPlaybackQuality();
 Object.assign(result,{error:error||null,first_frame_s:first===null?null:(first-started)/1000,
 observation_s:first===null?0:(performance.now()-first)/1000,displayed_frames:count,
 measured_fps:first===null?0:count/((performance.now()-first)/1000),
 max_frame_gap_ms:gaps.length?Math.max(...gaps):null,waiting_events:stalls,
 dropped_frames:q.droppedVideoFrames,total_video_frames:q.totalVideoFrames,
 width:video.videoWidth,height:video.videoHeight,audio_decoded_bytes:video.webkitAudioDecodedByteCount||0,
 video_decoded_bytes:video.webkitVideoDecodedByteCount||0,media_time_s:video.currentTime});
 window.__blinkResult=result;document.getElementById('result').textContent=JSON.stringify(result,null,2);
 fetch('/blink-plus-report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(result)});
 video.pause();hls.destroy();}
function frame(now,meta){if(finished)return;if(first===null){first=now;document.getElementById('status').textContent='Playing '+label;setTimeout(()=>finish(),20000);}
 if(last!==null)gaps.push(now-last);last=now;count++;video.requestVideoFrameCallback(frame);}
video.requestVideoFrameCallback(frame);
video.addEventListener('waiting',()=>{if(first!==null)stalls++;});
video.addEventListener('error',()=>finish('media_error_'+(video.error?video.error.code:'unknown')));
hls.on(Hls.Events.ERROR,(_,d)=>{result.errors.push({type:d.type,details:d.details,fatal:d.fatal});if(d.fatal)finish(d.details);});
hls.on(Hls.Events.MANIFEST_PARSED,()=>video.play().catch(()=>finish('play_rejected')));
hls.loadSource(source);hls.attachMedia(video);setTimeout(()=>finish('timeout'),70000);
</script></body></html>"""


@pytest.mark.parametrize(
    "camera_id", os.environ.get("BLINK_PLUS_LIVE_CAMERA_IDS", "").split(",")
)
async def test_browser_hls(
    hass, enable_custom_integrations, socket_enabled, monkeypatch, camera_id
):
    import logging

    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    import pytest_socket
    from pytest_homeassistant import plugins

    pytest_socket.socket_allow_hosts(["0.0.0.0/0", "::/0"], allow_unix_socket=True)
    monkeypatch.setattr("socket.getaddrinfo", plugins._real_getaddrinfo)
    raw = json.loads(
        Path(os.environ["BLINK_PLUS_AUTH_FILE"]).read_text(encoding="utf-8")
    )
    entry = MockConfigEntry(
        domain="blink_plus",
        title="Playback validation",
        unique_id="browser-validation",
        data=raw,
        options={"max_live_seconds": 90, "reconnect_cooldown": 5},
    )
    entry.add_to_hass(hass)
    session = ClientSession(connector=TCPConnector(resolver=ThreadedResolver()))
    server = None
    report = asyncio.get_running_loop().create_future()
    try:
        with patch(
            "custom_components.blink_plus.coordinator.async_get_clientsession",
            return_value=session,
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        c = next(
            c
            for c in entry.runtime_data.api.cameras.values()
            if str(c.camera_id) == camera_id
        )
        camera = next(
            e for e in hass.data["camera"].entities if getattr(e, "camera", None) is c
        )
        stream = await camera.async_create_stream()
        stream.add_provider("hls")
        url = stream.endpoint_url("hls")
        page = HTML.replace("__LABEL__", json.dumps(c.name)).replace(
            "__SOURCE__", json.dumps(url)
        )
        hls_js = Path(
            Path(__file__).resolve().parents[2] / ".browser-assets" / "hls.min.js"
        ).read_bytes()

        class Page(HomeAssistantView):
            url = "/blink-plus-test"
            name = "blink_plus:test_page"
            requires_auth = False

            async def get(self, request):
                await stream.start()
                return web.Response(text=page, content_type="text/html")

        class Ready(HomeAssistantView):
            url = "/blink-plus-ready"
            name = "blink_plus:ready"
            requires_auth = False

            async def get(self, request):
                return web.json_response({"camera": c.name, "camera_id": camera_id})

        class Script(HomeAssistantView):
            url = "/blink-plus-hls.js"
            name = "blink_plus:hls_js"
            requires_auth = False

            async def get(self, request):
                return web.Response(body=hls_js, content_type="application/javascript")

        class Report(HomeAssistantView):
            url = "/blink-plus-report"
            name = "blink_plus:report"
            requires_auth = False

            async def post(self, request):
                value = await request.json()
                if not report.done():
                    report.set_result(value)
                return web.json_response({"ok": True})

        for view in (Page, Ready, Script, Report):
            hass.http.register_view(view())
        server = TestServer(hass.http.app, host="127.0.0.1", port=8129)
        await server.start_server()
        print("BROWSER_READY " + c.name, flush=True)
        result = await asyncio.wait_for(report, 100)
        print("BROWSER_RESULT " + json.dumps(result), flush=True)
        folder = Path(__file__).resolve().parents[2] / ".validation"
        folder.mkdir(exist_ok=True)
        (folder / (camera_id + "-browser.json")).write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        assert result["error"] is None
        assert result["width"] > 0 and result["displayed_frames"] >= 100
        assert result["observation_s"] >= 19
        assert result["waiting_events"] <= 2
        assert result["max_frame_gap_ms"] < 750
        assert result["dropped_frames"] / max(1, result["total_video_frames"]) < 0.02
        assert result["audio_decoded_bytes"] > 0
    finally:
        if getattr(entry, "runtime_data", None):
            await hass.config_entries.async_unload(entry.entry_id)
        if server:
            await server.close()
        await session.close()
        await asyncio.sleep(0.25)
        await hass.async_block_till_done()
