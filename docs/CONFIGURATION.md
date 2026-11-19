# Configuration

All integration settings are available from **Settings > Devices & services > Blink Plus > Configure**. Credentials and verification codes are entered during setup or reauthentication. Options changes reload the entry and may interrupt active playback.

## Polling and live video

- **Polling interval:** 300 seconds by default; range 30-3600. Controls refresh state after commands; motion otherwise follows polling (see [Motion sensors](#motion-sensors)). Polling does not send the Sync Module any commands (see [Sync Module load](#sync-module-load)).
- **Read the USB clip list every N minutes:** 0 (never) by default; range 0-1440. Only matters for a Sync Module 2 with a USB drive.
- **Live view enabled:** on by default. Disable to prevent new live streams and local recordings.
- **Maximum live duration:** 120 seconds; range 15-300.
- **Reconnect cooldown:** 30 seconds; range 5-300. Applies after a session reaches its time limit, fails, or is ended by the camera, so a player that keeps reconnecting cannot wake the camera repeatedly. Closing live view normally does not start the cooldown.

## Sync Module load

A Sync Module works on one request at a time. While it is busy, the Blink app shows "system busy" and live view can fail. Blink Plus keeps its polling away from the module and skips requests whose answer the same poll already has:

| On every poll, blinkpy would | Blink Plus instead |
|---|---|
| Request each network's state (armed, online) separately | Takes it from Blink's overview (homescreen), which the same poll already loads |
| Ask a Sync Module 2 for its USB clip list, which makes the module scan the drive | Asks only every N minutes as configured; never with the default 0 |
| Make the module upload every new USB clip to the cloud | Never |
| Ask every outdoor camera for its signals (calibrated temperature) | At most once an hour per camera |

No poll runs while a camera of the account is starting or showing a live view.

These replacements apply only to Blink Plus's own connection; the built-in Blink integration is not affected. blinkpy ships with Home Assistant, so an update can change it. If a replaced method is missing, Blink Plus logs a warning and keeps blinkpy's behaviour for that part. Diagnostics list which reductions are active (`blinkpy_load_reductions`).

## Local recording

- **Recording duration:** 30 seconds; range 15-60. Maximum live duration must allow the recording plus 10 seconds for startup.
- **Recording directory:** empty by default, selecting the first configured HA media directory with a `blink_plus` subdirectory. A custom path must be permitted by HA's allowed-directory rules. Grant additional directory access in HA configuration only if needed.

Local files persist across reloads and restarts. Manage disk space and retention yourself. Successful completion updates the camera's `last_local_recording` attribute and emits `blink_plus_recording_completed`. Cloud browsing does not list these files; use HA's local media browser for directories exposed there.

## Cloud media

- **Cloud browsing enabled:** on by default.
- **History window:** 30 days; range 1-90.
- **Maximum listed clips:** 1000; range 50-5000.
- **Catalogue refresh interval:** 60 seconds; range 15-600. This controls catalogue reuse when browsing, rather than continuously downloading clips.
- **Temporary cache:** 128 MiB; range 16-1024. Full clip downloads are cached privately so HA can support seeking. Size limits apply; oversized clips may be rejected. Cache files are removed when the entry unloads.

These settings do not change Blink cloud retention or subscription entitlement. No recordings are downloaded until requested by a player.

## Pan/tilt mount

Select only cameras with a compatible mount; the default list is empty. Selection exposes left, right, up, down, and home buttons.

- Pan step: 15 by default; range 1-45.
- Tilt step: 10 by default; range 1-30.
- Invert pan: on by default.
- Invert tilt: off by default.

A mount command uses a live connection. This feature does not turn a fixed camera into a motorized camera.

## Entity availability

Temperature is reported in Fahrenheit by Blink and converted by HA. Voltage readings are converted from hundredths of a volt. Battery bars and Sync Module bars remain raw reported scales, not invented percentages. Missing values do not create fabricated sensor readings. Additional supported sensors can appear after later polls.

Network arming and camera motion detection are separate switches. A camera can have detection disabled while its network remains armed.

## Automation examples

Replace these illustrative entity IDs with the ones created on your system.

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.example_camera_take_snapshot
```

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.example_camera_record_local_clip
```

```yaml
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.example_network_armed
```

Use HA's automation UI to choose actual entities and triggers. Motion is polled, so a Motion sensor turns on up to one polling interval after the event; assess suitability before relying on it for time-sensitive automations.

## Two-way talk

Talk uses the existing Live view option and camera entity. Open live video before posting audio. No new account login, entity or talk-specific option is required when updating from 0.1.x.

A compatible client captures the microphone and streams AAC-LC, 16 kHz mono, in ADTS frames to POST /api/blink_plus/talk/{entity_id}, with HA authentication and camera control permission. One talker is accepted per camera and each request is limited to 60 seconds. Browser microphone access requires HTTPS or trusted localhost.

See the [complete talk guide](TWO_WAY_TALK.md) for upgrade steps, a command-line example, status codes, client lifecycle and tested camera scope.


## Native HA microphone button

For 0.3.0, register /blink_plus/frontend/blink-plus-ptt.js?v=0.3.0 as a JavaScript module resource, then add a custom:blink-plus-ptt element with your camera entity. The [native PTT guide](NATIVE_PTT.md) provides a complete live camera example.

The element uses your authenticated HA session and camera control permission. The integration encodes microphone audio using HA's existing media libraries. Browser capture requires HTTPS or trusted localhost. Hold to speak, release to stop, and wait for stopping to finish before pressing again.


### Sidebar page

**Show the Blink Plus page in the sidebar** (on by default) adds a page listing every camera with live view on request and its controls. Switch it off to remove the page; the Blink Plus camera card stays available for your own dashboards. See the [dashboard guide](DASHBOARD.md).

### Motion sensors

Each camera's **Motion** binary sensor turns on when Blink lists a newer clip for that camera, and off again two minutes later. Blink Plus reads Blink's list of the last 30 minutes of clips at every poll and after every command (a snapshot, a switch), so a clip that Blink lists late still counts.

- The sensor follows recorded clips. Motion that records nothing (system disarmed, the camera's motion detection off, the camera inside its retrigger time) does not turn it on.
- It turns on at the first poll or command after Blink lists the clip. With the default 300-second polling interval that is up to five minutes after the event; a shorter interval shortens the delay.
- Clips already listed when Home Assistant starts are not reported as new motion.
- A clip saved only to a Sync Module's USB storage is reported only if the Blink library detects it.

### Camera lighting

Two camera models get a light entity automatically:

| Camera | Product type | Entity |
|--------|--------------|--------|
| Blink Wired Floodlight | `superior` | **Floodlight** |
| Blink Mini 2 | `hawk` | **Spotlight** |

Both are on/off only. Other models do not get this entity. Battery floodlight
accessories, brightness and the lamp's timer settings are not exposed.

**State.** From 1.0.2 the entity shows the lamp state Blink reports for the
camera, so it also follows changes Home Assistant did not make:

- The lamp's own timer switching it off. A manually switched lamp turns itself
  off after the duration set in the Blink app, unless that is set to stay on.
- Motion lighting, and switching it in the Blink app.

Blink Plus reads the state when it starts, on every poll (the polling interval
option), about 6 and 26 seconds after a command, and every 30 seconds while the lamp
is on, for up to 10 minutes. A lamp switched on outside Home Assistant is
therefore noticed at the next poll, not instantly. If Blink's report cannot be
read, the entity keeps the last accepted command and is marked as an assumed
state until a report arrives.

**During live view.** Blink refuses its normal lights request while a live view
is open on the camera. From 1.1.2, when the live view is Blink Plus's own (a
dashboard card, the sidebar page, or any Home Assistant player), the lamp is
switched on the live session instead, as the Blink app does, and the camera
confirms it at once. While that session is open the entity also follows the
lamp instantly. A live view held by the Blink app, or a recording in progress,
still makes Blink answer busy; try again afterwards.

Floodlight added in 1.0.1; reported state and the Mini 2 spotlight in 1.0.2.
Example automation action:

```yaml
action: light.turn_on
target:
  entity_id: light.driveway_floodlight
```

### Login renewal

There is nothing to configure. Blink Plus stores the tokens Blink returns at
sign-in, together with the registered hardware ID; it never stores the password
or verification code. From 1.0.1 it renews the token itself when Home Assistant
starts and shortly before the token expires.

- Blink refuses the token (HTTP 400 or 401): Home Assistant shows
  **Reauthenticate**. Sign in again; the hardware ID is kept.
- Blink is unreachable, times out, throttles or returns a server error: the
  entry retries on its own and no sign-in is requested. Entities are unavailable
  until Blink answers again.

An entry that holds no refresh token (not produced by current sign-ins) uses
blinkpy's own startup instead, as earlier versions did.
