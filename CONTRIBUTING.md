# Contributing

Open an issue describing the camera model, HA version, integration version, and reproducible behavior before a substantial change. Use synthetic account/device data in tests. Do not commit account sessions, credentials, real device IDs, recordings, or private network details.

## Automated validation

Use Python 3.14 in a virtual environment:

```sh
pip install pytest-homeassistant==2026.11.1 blinkpy==0.25.9 numpy==2.3.2 av==19.0.0 ha-ffmpeg==3.2.2 PyTurboJPEG==1.8.3
python -m unittest discover -s tests -v
PYTHONPATH=. pytest -q tests/ha --asyncio-mode=auto -p no:respx -o asyncio_default_fixture_loop_scope=function
```

The normal suite uses no Blink account. The `test_*_manual.py` groups require explicit environment opt-in and an existing private session file; review each test before enabling it. Some operate cameras, motion/arming controls, and mount positions or write recordings. Never run live tests against an account without its owner's authorization. Browser validation additionally needs a locally supplied hls.js file in `.browser-assets/hls.min.js`; it is not bundled or fetched automatically.

`tools/browser_driver.cjs` is an optional Windows Edge/Node browser harness. Set `BLINK_PLUS_SSH_HOST` to your SSH alias, optionally `BLINK_PLUS_SSH_KEY`, and `BLINK_PLUS_BROWSER_COUNT` to the expected camera count. Its tunnel connects to an isolated loopback test server, not a production HA instance.

## Release checklist

1. Update manifest version, changelog, documentation, and manual-install filename.
2. Inspect tracked files for secrets, private metadata, recordings, and caches.
3. Validate UTF-8, local documentation links, and mobile/desktop README rendering.
4. Run tests and official HACS/hassfest checks with no ignored validators.
5. Publish an immutable version tag and full GitHub release after CI succeeds. Build manual-install assets from that commit, with SHA256 checksums.
6. Verify release/tag targets and assets. Never silently retag an existing release.

HACS custom-repository support and acceptance into the default catalog are separate. Do not claim catalog acceptance until the repository is actually listed.
