# Changelog

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
