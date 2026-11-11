# Home Assistant dashboard push-to-talk

Blink Plus 0.3.0 adds a microphone button directly to an HA dashboard camera view. It uses the signed-in HA user's connection and encodes microphone audio inside Blink Plus.

## Add the resource

After installing 0.3.0 or newer and restarting HA, open Settings > Dashboards > Resources. Advanced mode may be needed to show Resources.

Add /blink_plus/frontend/blink-plus-ptt.js?v=0.3.0 as a JavaScript module. Refresh the dashboard after adding or updating the resource.

## Place it over live video

Replace the sample camera entity with your Blink Plus camera.

~~~yaml
type: picture-elements
camera_image: camera.example_camera
camera_view: live
elements:
  - type: custom:blink-plus-ptt
    entity: camera.example_camera
    style:
      left: 4%
      top: 6%
      transform: none
~~~

Existing pan/tilt elements can share the same picture-elements card. The button can also be used as a standalone custom:blink-plus-ptt card with an entity setting beneath an existing live camera card.

## Use it

Open live video and wait for it to play. Hold the microphone button while speaking and release to stop. Wait for the label to return to Hold to talk before the next press. Space or Enter also works while the button has focus. Allow microphone permission if prompted, then hold again if the prompt ended the first press.

Use HA over HTTPS, such as an existing Home Assistant Cloud connection, or a browser-trusted localhost connection. Plain HTTP LAN or Tailscale IP addresses cannot capture microphone audio. The button shows an instruction when capture is unavailable.

Talk ends on release, focus loss, page hiding, navigation, disconnect or the one-minute hold limit. A second talker on the same camera is refused. Camera control permission is required.

## Transport and privacy

The browser sends bounded 100 ms packets of 16 kHz mono PCM over HA's authenticated websocket. The integration encodes AAC-LC in memory using HA's existing media dependencies and transmits it over the active camera connection. It creates no microphone recording file.

The websocket session is bound to its original connection, camera and live stream. Audio packet order is checked, buffers are bounded and disconnect/unload cleanup releases the speaker and talk lock. The existing ADTS HTTP talk endpoint remains available for other compatible clients.

Camera speaker support depends on model and account behavior. A Mini-class camera has been verified through HA's native dashboard button and the original HTTP/client path. Verify the actual speaker when configuring a new camera model.
