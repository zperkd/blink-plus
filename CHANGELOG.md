# Changelog

## 0.1.3 - 2026-11-10

Snapshot reliability, found while moving a seven-camera home to the integration.

- Fixed: **Take snapshot** often failed with a timeout on battery cameras and when another Blink request was running. Blink handles one command at a time per network and answers "busy" meanwhile; that answer was treated as accepted, so the button then waited for a picture that was never taken. A busy answer is now retried (three attempts, six seconds apart) and reported clearly if Blink stays busy.
- Changed: while waiting for the new picture the integration now checks Blink's one-request overview every three seconds instead of running a full refresh every eight. A full refresh also downloads every camera's thumbnail and recent clip, which made the wait slow enough to run into the command timeout. One full refresh still runs once the new picture is listed.
- Changed: a snapshot that Blink does not publish within about 45 seconds now ends with "Blink did not publish a fresh snapshot in time" instead of a generic failure.

Validation: 70 automated tests plus official HACS and hassfest checks. Snapshots were checked on real cameras with this version; see the release notes.

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
