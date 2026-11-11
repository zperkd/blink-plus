# Blink Plus validation - 2026-11-10

## 0.2.0 talk validation

The 0.2.0 release adds independent-session talk support and API safeguards. The integration suite passes 83 automated tests, with five live groups skipped in normal runs. Official release CI is recorded in GitHub Actions.

A Mini-class camera played synthetic AAC tones and the owner's actual voice through a custom browser dashboard. The final successful voice test used the production HA talk endpoint with the official Blink app closed. Preserving only the media token was insufficient in an earlier endpoint test. The validated sequence also sends the initial keepalive, uses the talk-control sequence and waits for a fresh reply.

The separate dashboard's browser test sent 29 microphone packets in roughly three seconds, received successful start/data/stop responses and verified microphone tracks ended on release. Isolated client UI checks verified permission-denied feedback and close-during-talk cleanup. The complete dashboard suite passed 293 tests, followed by 64 affected checks after small cleanup changes. Those client checks belong to the separate dashboard and are additional to the integration's 83 tests.

Talk speaker playback was verified on one Mini-class camera. Other camera speakers, actual wall-panel microphone hardware, phone/browser combinations, casting and long-term reliability remain open test areas. The microphone UI is supplied by a compatible client. See [Two-way talk](TWO_WAY_TALK.md).

## Historical 0.1.0 viewing, recording and cloud validation

The following results document the original 0.1.0 validation run. The original production-state statements describe that historical run. The owner subsequently installed Blink Plus and verified the 0.2.0 talk development build in production.

Test environment: isolated Home Assistant 2026.11.1 / Python 3.14 on the Pi. Production HA independently reports the same Core version. Browser: headless Edge 157 on a separate Windows host, connected to the isolated loopback-only HTTP test server through an SSH tunnel. Production HA was not restarted or modified.

## Final browser results

Each sample measured 20 seconds from the first displayed frame. AAC audio decoded on every camera. No buffering/waiting events were observed in this final run.

| Camera | Native resolution | Displayed fps | Browser startup | Dropped frames |
|---|---|---:|---:|---:|
| Mini A | 1920x1080 | 19.94 | 10.79 s | 2/405 |
| Battery A | 1920x1080 | 29.89 | 14.09 s | 1/603 |
| Doorbell | 1440x1440 | 29.95 | 13.18 s | 1/604 |
| Mini B | 1920x1080 | 14.99 | 10.19 s | 0/304 |
| Battery B | 1920x1080 | 29.88 | 11.28 s | 1/603 |
| Battery C | 1280x720 | 24.00 | 11.49 s | 0/484 |
| Battery D | 1920x1080 | 29.88 | 14.09 s | 2/604 |

Maximum frame gap was 116.7 ms. Final browser suite: 7 passed, clean teardown. Native frame rate varies with camera configuration/conditions; earlier Mini A samples differed. This is a short validation sample, not a long-term reliability claim.

## Real controls and sensor capabilities

- Fresh snapshots: Mini A 17.90 s; Battery A 22.02 s; Doorbell 21.06 s; Mini B 18.96 s; Battery B 19.19 s; Battery C 22.47 s; Battery D 20.93 s. JPEG data and changed thumbnail metadata were verified through HA button services. One earlier snapshot attempt failed transiently before any arming/motion changes; the repeat and all final per-camera checks passed.
- Mini A motion detection toggled to the opposite state, verified from refreshed cloud data, then restored to OFF.
- Network arming toggled, verified, and restored to ARMED.
- Mini B mount acknowledged left/right/up/down/home. Its exact original position was restored and acknowledged.
- A final independent session confirmed the network was armed and Mini A motion detection was off.
- Outdoor cameras reported real Fahrenheit temperature, calibrated temperature, hundredths-of-volt battery values, low/OK state and Wi-Fi dBm. The doorbell reported battery bars and sync bars. The Minis omitted unsupported readings. The HA test environment also verified automatic temperature-unit conversion and late sensor discovery.

## Local recordings

HA's actual record button produced native H.264/AAC MP4s. Both streams were decoded from every saved file.

| Camera class | Requested duration | File duration | File size | Video/audio frames decoded |
|---|---:|---:|---:|---:|
| Mini A Mini | 15 s | 16.237 s | 1,469,690 bytes | 240 / 250 |
| Battery A battery | 15 s | 15.524 s | 2,897,590 bytes | 464 / 240 |
| Doorbell doorbell | 15 s | 14.567 s | 1,952,741 bytes | 436 / 225 |

The three test recordings remain on the Pi under the isolated development workspace's `.validation/recordings` directory. They were not copied into OneDrive, published, or installed into production HA.

## Cloud listing and retrieval

The existing authenticated Blink media API works; phone instrumentation was not needed. The integration's real HA media-source test:

- Browsed 1,000 clips (the configured limit), grouped into seven camera folders.
- Resolved a playable signed HA URL without exposing a Blink URL or token to the player.
- Rejected unsigned access with HTTP 401.
- Downloaded an actual 4,763,759-byte H.264/AAC MP4 (28.42 seconds) into the private temporary cache.
- Served a signed `bytes=0-4095` request as HTTP 206 with 4,096 bytes, even though Blink's origin ignored a direct Range request.
- Retrieved a 32,334-byte JPEG thumbnail and removed the cloud cache on unload.

Cloud pagination, stale/deleted filtering, origin restrictions, duplicate-download caching, configured size bounds, signed URLs, anonymous rejection, range responses and cancellation/unload behavior have automated coverage.

## Automated checks and fixes

58 automated tests pass; five explicitly opted-in live-test groups are skipped during normal runs. Lint checks for Python correctness pass, source/tests were formatted, and the official HA hassfest validator reports zero invalid integrations. Official GitHub HACS and hassfest checks and test results are available in the repository Actions history. Catalog acceptance is separate from automated validation.

Fixed during validation: Configure while unloaded; reauthentication after a failed control refresh; backend option validation; local recording with allowed-directory and session-duration guards; private cloud clip browsing/proxy/cache; and download cancellation/cleanup.

An experimental shortened stream-probing mode was rejected: it saved little startup time but removed Mini B audio and caused a multi-second pause. It is absent from the final build. Standard probing restored audio and smooth playback. Startup remains 10-14 seconds in the final browser samples.

## Limits of the evidence

Fresh credential/MFA entry was simulated in flow tests; actual live tests authenticated with the existing saved Blink session. Settings form logic/schema was tested, not visually exercised in the HA frontend. Audio decoding was verified; a human did not listen to the output. Phone UX, casting, long-term operation, production installation/migration, unsupported camera models, Sync Module USB media, push events and two-way talk are outside this completed validation run.

The original HA integration, dashboards and Pi blink-live service remain unchanged. Release packaging does not change that production-installation status.
