# Changelog

## 0.3.0 - 2026-11-10

Native Home Assistant dashboard push-to-talk and reliable repeated holds.

- Added the bundled custom:blink-plus-ptt element for picture-elements live video overlays and standalone cards, with an HA microphone icon, hold/release and Space/Enter support.
- Added authenticated, connection-owned HA websocket microphone sessions and in-memory PCM-to-AAC encoding using HA's existing media dependencies.
- Added bounded ordered audio packets, one talker per camera, one-minute holds, idle cleanup and cancellation-safe disconnect/unload cleanup.
- Fixed repeated talk in the same live session. Speaker start/stop use fixed control IDs 3 and 4 each time. These identifiers previously increased after the first hold.
- Fixed re-pressing during speaker shutdown. The button shows Finishing until the previous stop completes, including a release while talk is still opening.
- Added microphone permission/HTTPS feedback and a hold-again hint when a browser prompt ends the first press.
- Added a [native HA setup guide](docs/NATIVE_PTT.md), card YAML, resource instructions, updated README/configuration/architecture and explicit test evidence.

The included element captures the microphone directly in HA. Existing clients can continue to use the AAC HTTP endpoint. Add the JavaScript module resource and configure the element after updating and restarting HA. Camera speaker verification is currently limited to one Mini-class camera.


## 0.2.0 - 2026-11-10

Two-way talk through the existing live media connection, with a documented API for compatible clients.

- Added authenticated POST /api/blink_plus/talk/{entity_id}. It receives ADTS-framed AAC-LC at 16 kHz mono, reconstructs split frames, validates the format, paces uploads in real time and reports the transmitted frame count.
- Added camera control-permission enforcement, one active talk upload per camera, a 60-second request lifetime, malformed/empty-audio rejection and cleanup when the client or live session ends. An old upload cannot send audio to or stop a replacement session.
- Fixed talk remaining silent in independent sessions by preserving the liveview_token from Blink's live-view response and reproducing the initial media keepalive and speaker-control sequence. The relay waits for a fresh speaker acknowledgement before sending audio.
- Added regression coverage for token placement, unchanged receive-only handling when the token is absent, oversize token rejection, empty/stale acknowledgements, simultaneous talkers, invalid audio, request timeout and replacement-session ownership.
- Updated the README, configuration and architecture notes, validation evidence and dedicated [two-way talk how-to](docs/TWO_WAY_TALK.md). The guide includes an ffmpeg/curl example, browser microphone requirements, API responses and model limits.

Live voice and tones were heard through a Mini-class camera with the official app closed. The voice test used a separate custom browser dashboard with hold/release controls, microphone cleanup and server-side encoding. A compatible client supplies the microphone UI when using this integration. Doorbell and outdoor-camera speakers need additional model-specific testing.

Validation for the release includes 83 automated integration tests and five opt-in live groups skipped during normal runs. Existing seven-camera viewing and recording evidence remains in [Validation](docs/VALIDATION.md). Update through HACS / Marketplace and restart HA. Existing entities and options carry over from 0.1.x.


## 0.1.3 - 2026-11-10

Snapshot reliability and a direct live stream, both from moving a seven-camera home to the integration.

- Added: **direct live stream** at `/api/blink_plus/live/<camera entity id>` for low-delay players. An authenticated client (a long-lived access token, like any Home Assistant API call) receives the camera's native MPEG-TS (H.264 and AAC) as it arrives, without the second or more that HLS packaging adds. It is one more viewer of the camera's relay: session limit, cooldown and sharing apply, and the camera session ends as soon as the last viewer disconnects. Home Assistant's own live view is unchanged.

- Fixed: **Take snapshot** often failed with a timeout on battery cameras and when another Blink request was running. Blink handles one command at a time per network and answers "busy" meanwhile; that answer was treated as accepted, so the button then waited for a picture that was never taken. A busy answer is now retried (three attempts, six seconds apart) and reported clearly if Blink stays busy.
- Changed: while waiting for the new picture the integration now checks Blink's one-request overview every three seconds instead of running a full refresh every eight. A full refresh also downloads every camera's thumbnail and recent clip, which made the wait slow enough to run into the command timeout. One full refresh still runs once the new picture is listed.
- Changed: a snapshot that Blink does not publish within about 45 seconds now ends with "Blink did not publish a fresh snapshot in time" instead of a generic failure.
- Changed: new icon and logos, the lowercase name on a sky-blue tile with a plus badge. It is original lettering, not Blink's own logo artwork.

Validation: 73 automated tests plus official HACS and hassfest checks. On a real seven-camera system with this version, snapshots succeeded on five of five cameras tried (18-26 seconds each), and the direct stream played smoothly with sound in Chrome on four cameras, about 0.9 seconds from a pan-tilt command to the picture moving.

## 0.1.2 - 2026-11-10

Hardening release. No new features and no option or entity changes.

- Changed: Home Assistant's per-camera **Preload stream** setting is now ignored for Blink Plus cameras. With it on, a camera was woken again after every session limit and cooldown, indefinitely, with nobody watching. A warning is logged when the setting is found enabled. A camera with the setting on may still start one short session when Home Assistant starts.
- Added: live view checks that the installed blinkpy still provides what the relay builds on, and otherwise fails with a clear `incompatible_blinkpy` error. A contract test and a CI job against the newest blinkpy release warn about upstream changes early.
- Changed: local recording finds its camera entity through the integration's own registry instead of Home Assistant internals.
- Fixed: per-clip download locks are released once no request uses them, instead of accumulating for every clip ever opened.

Validation: 66 automated tests plus official HACS and hassfest checks. No new live camera tests were run for this release; the live results in [docs/VALIDATION.md](docs/VALIDATION.md) are from 0.1.0.

## 0.1.1 - 2026-11-10

Bug-fix release. No new features and no option or entity changes.

- Fixed: the integration reloaded itself every time Blink refreshed its login token, which dropped live streams, cleared the cloud clip cache, and briefly made entities unavailable. It now reloads only when options change.
- Changed: the reconnect cooldown no longer starts when the last viewer closes live view normally, so live view can be reopened immediately. It still applies after a session reaches its time limit, fails, or is ended by the camera.
- Fixed: a camera that does not start streaming within 20 seconds is now logged and reported in diagnostics as `start_timeout` instead of `session_limit`.
- Diagnostics report the installed version from the manifest.

Validation: 60 automated tests plus official HACS and hassfest checks. No new live camera tests were run for this release; the live results in [docs/VALIDATION.md](docs/VALIDATION.md) are from 0.1.0.

## 0.1.0 - 2026-11-10

Initial community release.

- UI account setup, MFA, reauthentication, and configurable options.
- Native live H.264 video and AAC audio with per-camera relays, session bounds, and cleanup.
- Cached images and fresh snapshot buttons.
- Local MP4 recording with allowed-directory and duration checks.
- Authenticated cloud media browsing, thumbnails, bounded private caching, and seekable playback.
- Motion/arming switches and capability-dependent camera sensors.
- Optional pan/tilt mount buttons and axis controls.
- Redacted diagnostics, original local brand assets, HACS layout, and official validation workflow.

Validation includes 58 automated tests and separate opt-in live checks across seven cameras. Browser startup measured 10.19-14.09 seconds in final samples. See [full results](docs/VALIDATION.md). This release does not include push events, two-way talk, USB clips, or all Blink app settings.
