# Changelog

## Unreleased

Polling leaves the Sync Module alone.

- On every poll, blinkpy asked a Sync Module 2 with a USB drive for its clip list (the module scans the drive) and made the module upload every new USB clip to the cloud. While the module works on one of these, the Blink app answers "system busy" and live view can fail. Blink Plus now reads the USB clip list only when **Read the USB clip list every N minutes** is above 0 (default 0 = never) and never makes the module upload USB clips during a poll.
- Two requests whose answer the poll already has are skipped as well: each network's state now comes from the overview (homescreen) the same poll loads, and every outdoor camera is asked for its signals (calibrated temperature) at most once an hour instead of on every poll.
- No poll runs while one of the account's cameras is starting or showing a live view.
- The polling interval can now be set down to 30 seconds.
- These changes only apply to Blink Plus's own connection; the built-in Blink integration keeps blinkpy's behaviour. If a Home Assistant update ships a blinkpy without one of the replaced methods, Blink Plus logs a warning and uses blinkpy's behaviour for that part. Diagnostics list which reductions are active (`blinkpy_load_reductions`).

## 1.1.3 - 2026-11-17

Motion sensors follow Blink's clip list.

- Fixed the Motion binary sensors missing most motion. They showed a library flag that covers only a clip started since the previous refresh and is cleared by the next one. A snapshot refreshes twice before Home Assistant is told, so on an installation that takes snapshots on a timer the flag was usually gone before it could be seen; one of the owner's cameras recorded a clip every day for a week without its sensor turning on once.
- Blink Plus now reads Blink's list of recent clips itself at every poll and after every command, and turns a camera's Motion sensor on for two minutes when a newer clip appears for it. A clip Blink lists late, up to 30 minutes after it started, still counts. This is one extra small request per poll.
- Clips already listed when Home Assistant starts are not reported as new motion. A failed clip request keeps the previous answer and never fails the poll.
- Motion is still polled: the sensor turns on at the first poll or command after Blink lists the clip, which with the default interval is up to five minutes after the event. No changes to entities, stored data or the login.

## 1.1.2 - 2026-11-16

The light works during live view.

- Fixed the Floodlight and Spotlight being refused with "Blink is busy" while that camera's live view was open. Blink rejects its normal lights request for as long as a live session exists, so during one Blink Plus now switches the lamp on the live session itself, the way the Blink app does. The camera confirms the change in about a tenth of a second.
- While live view is open the light entity follows the lamp instantly: the camera reports its lamp on the session when it opens and whenever it changes, including when its own timer switches it off.
- With no live view open nothing changes: the normal request is used and the state is read from Blink as before. If another app holds a live view on the camera, Blink still answers busy.
- Verified on a Mini 2 spotlight and a Wired Floodlight: on and off during live video, each confirmed by the camera and by Blink's reported state.

## 1.1.1 - 2026-11-16

- Added a **Stop live view** button to the Blink Plus camera card, next to the camera's name. It closes the video at once and does not restart when you return to the tab; the same button reads **Start live view** when nothing is playing. The camera's own session ends shortly afterwards, when Home Assistant releases the stream.

## 1.1.0 - 2026-11-16

Everything works after installation: a sidebar page, a complete camera card and automatic loading.

- Added a **Blink Plus** page to the Home Assistant sidebar. It lists every Blink Plus camera with its picture, live view on request, controls and readings, plus arm/disarm for each Blink system. A new option, **Show the Blink Plus page in the sidebar** (on by default), removes it.
- Added the **Blink Plus camera** card (`custom:blink-plus-camera-card`). One line of configuration, the camera entity, gives live video with the browser's player controls (pause/play, time bar, mute and volume, full screen), Hold to talk, a light button, a pan/tilt pad, New picture, Record clip, Motion detection and the camera's readings. Each part is found through the camera's device and can be hidden with a card option.
- The card plays video in its own player, using Home Assistant's documented `camera/stream` call and a bundled copy of hls.js 1.7.4 (Apache-2.0). It does not use Home Assistant's internal camera player, so a frontend update cannot remove the controls.
- The integration now loads its dashboard code by itself. Adding `/blink_plus/frontend/blink-plus-ptt.js` under Resources is no longer needed; an existing entry keeps working and can be removed.
- Talk and pan/tilt buttons appear on the card only while live video is playing, because they act on the live session. A hidden browser tab stops its live video after 15 seconds.
- Added a [dashboard guide](docs/DASHBOARD.md). No changes to entities, stored data or the login.

## 1.0.2 - 2026-11-16

Real light state, and the Mini 2 spotlight.

- The Floodlight entity now shows the state Blink reports (`light_status` in the camera's settings) instead of the last command sent. It follows the lamp switching itself off on its timer and changes made by motion or the Blink app. The state is read at startup, on every poll, about 6 and 26 seconds after a command, and every 30 seconds while the lamp is on (for up to 10 minutes).
- Added a **Spotlight** light entity for Blink Mini 2 cameras (product type `hawk`), using the same on/off command and reported state.
- If Blink's report cannot be read, the entity keeps the last accepted command and is marked as assumed, as in 1.0.1.
- Verified on a Wired Floodlight: on, off and the lamp's own automatic switch-off were all reported by Blink. On a Mini 2, Blink accepted the commands and reported on and off.
- The existing Floodlight entity keeps its entity ID and unique ID.

## 1.0.1 - 2026-11-16

Login renewal that survives Blink outages, and on/off control for Wired Floodlight cameras.

- Fixed a Blink outage or throttled token request being shown as a Reauthenticate prompt. Blink Plus now renews its stored token itself: only a token Blink refuses (HTTP 400/401) asks for a new login; an unreachable or failing Blink is retried. This covers Home Assistant restarts and routine renewals while running. Entries without a stored refresh token keep the previous startup path.
- Added a native on/off light entity for Blink Wired Floodlight cameras (superior). State is unknown until a successful command and assumed thereafter; Blink does not report external light changes through blinkpy. Covered by automated tests; not yet verified on a physical floodlight at release.
- Tokens keep being stored without the password or verification code; the renewal request contains the refresh token and registered hardware ID only.
- Added tests for token renewal, restart and running-entry outages, refused tokens, and a blinkpy compatibility check for the calls the renewal relies on.

Version numbering moves from 0.3.0 to 1.0.1. There is no 1.0.0 release, no breaking change and no migration: entities, options and the stored login are kept.

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
