"""Allow loopback protocol tests alongside HA's offline test harness."""

import pytest


@pytest.fixture(autouse=True)
def protocol_loopback(request):
    if request.node.path.name == "test_transport.py":
        request.getfixturevalue("socket_enabled")
