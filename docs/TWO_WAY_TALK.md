# Two-way talk

Blink Plus 0.2.0 adds authenticated audio transmission to a camera during live view. Talk was verified with a Mini-class camera using a test tone and an owner's voice through a custom browser dashboard, including an independent session with the Blink app closed.

A compatible client supplies microphone capture and the Talk button. HACS installs the Home Assistant integration and its talk API. The separate Home Lab dashboard used for the owner's voice test has its own microphone controls and encoder. This repository documents the integration API for client developers and command-line use.

## Update and prerequisites

1. Download Blink Plus 0.2.0 in HACS / Marketplace and restart Home Assistant.
2. Keep **Live view** enabled in the integration's Configure menu.
3. Find the integration's camera entity, for example camera.example_camera.
4. Open that camera's live video and wait until it plays. Keep the viewer open throughout talk.
5. Send AAC-LC audio at 16 kHz, mono, with ADTS framing to the endpoint below.

Existing Blink Plus entities and options carry over from 0.1.x. No new account login is normally needed. Back up your HA configuration before updating.

Browser microphone capture requires HTTPS or a browser-trusted localhost context and microphone permission. A browser should end capture on release, cancellation, focus loss, page hiding and viewer close. When a permission prompt ends the first press, press again after granting permission.

## Command-line how-to

The following Bash example needs ffmpeg, curl, a short WAV file and a Home Assistant long-lived access token from a user permitted to control the camera. Open live video in HA first.

Set your HA address and actual camera entity. Read the token interactively so its value stays out of the example and shell command history.

~~~sh
HA_URL='http://homeassistant.local:8123'
CAMERA='camera.example_camera'
read -r -s -p 'Home Assistant token ' HA_TOKEN
printf '\n'

ffmpeg -hide_banner -loglevel error -nostdin -i sample.wav -t 10 \
  -ac 1 -ar 16000 -c:a aac -b:a 24k -f adts pipe:1 |
  curl --fail-with-body --request POST --upload-file - \
    --header "Authorization: Bearer $HA_TOKEN" \
    --header 'Content-Type: audio/aac' \
    "$HA_URL/api/blink_plus/talk/$CAMERA"

unset HA_TOKEN
~~~

The file plays through the camera speaker. The integration paces uploaded frames to real time. On success the response contains the frame count, for example {"frames": 33} for a short sample. Ending the request closes talk while live video can continue. Close the video viewer when finished.

Use an HA address reachable from the client. Browser microphone access and the HTTP API connection each need the appropriate secure connection for your deployment.

## HTTP interface

| Item | Value |
|---|---|
| Method | POST |
| Path | /api/blink_plus/talk/{entity_id} |
| Authentication | HA bearer token |
| Permission | Control of that camera entity |
| Content type | audio/aac |
| Body | Complete ADTS-framed AAC-LC packets, 16 kHz, mono, one 1024-sample block per frame |
| Maximum upload lifetime | 60 seconds, also bounded by the live session |
| Concurrent talkers | One per camera |
| Successful response | JSON frame count |

The request can arrive in chunks of arbitrary sizes. The integration reconstructs frames, validates format, waits for the speaker acknowledgement and sends each frame over the camera's existing media connection.

| HTTP status | Meaning and next action |
|---|---|
| 200 | Audio frames were sent. Check the camera speaker for actual playback. |
| 400 | Audio is empty, incomplete, or has unsupported codec, rate or channels. Re-encode with the example settings. |
| 401 / 403 | Check HA authentication and camera control permission. |
| 408 | Talk exceeded 60 seconds. End each hold promptly and open a new upload for another hold. |
| 409 | Another talk request owns the camera. End it before retrying. |
| 503 | Open live view, wait for video, or reconnect after an ended/unacknowledged session. |

A successful upload reports transmitted frames. Physical playback also depends on the camera, its settings and the supported transport. Test the actual camera speaker when adding a model.

## Client lifecycle

Acquire the microphone after a deliberate press. A client that captures PCM or Opus must encode it to the required AAC format before posting. Browser MediaRecorder output varies by browser and needs conversion when it uses another codec or container.

Maintain one continuous request for one hold, with bounded input buffering. Release ends capture and the request. Muting incoming camera audio during a hold helps prevent feedback, then restore the previous mute state. A disconnected client should stop its encoder and release all microphone tracks.

The integration rejects a second talk request for the same camera and prevents an old request from sending to or stopping a replacement live session. Empty or malformed uploads are rejected. Camera control permission is checked independently of permission to view video.

## Privacy and tested scope

The integration handles talk audio in memory and sends it to Blink's media connection. It creates no talk recording file. A separate client controls its own capture, encoding and storage behavior. Keep HA credentials on a trusted client or its server and review diagnostics before sharing.

Live voice and tone playback were verified on one Mini-class camera. Speaker support on other Mini variants, doorbells and outdoor battery models, casting, and long-term operation need further testing. Existing seven-camera viewing results are recorded separately in [Validation](VALIDATION.md).

## Connection details

Blink's live-view response supplies a per-session liveview_token. The relay preserves it in the IMMI authentication header, sends the initial sequence-zero keepalive, opens talk using message type 0x17 and waits for a fresh type 0x18 reply. Audio uses message type 0x05. A final type 0x17 closes talk.

These are unofficial protocol details and can change. The token remains in memory. Talk starts inside Home Assistant using the existing Blink session.
