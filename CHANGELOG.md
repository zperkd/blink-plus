# Changelog

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
