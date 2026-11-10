"""Real Home Assistant lifecycle tests with Blink cloud calls mocked."""

from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest
from pytest_homeassistant.common import MockConfigEntry
from homeassistant.data_entry_flow import FlowResultType

DOMAIN = "blink_plus"


def fake_camera():
    return SimpleNamespace(
        serial="TEST123",
        name="Test camera",
        product_type="hawk",
        camera_type="mini",
        version="1",
        image_from_cache=b"cached-jpeg",
        temperature=None,
        temperature_calibrated=None,
        battery_voltage=None,
        battery_level=None,
        battery=None,
        wifi_strength=None,
        sync_signal_strength=None,
        last_record=None,
        motion_detected=False,
        motion_enabled=True,
        status=None,
        attributes={"motion_enabled": True},
        async_arm=AsyncMock(return_value=True),
        snap_picture=AsyncMock(return_value=True),
        record=AsyncMock(return_value=True),
        init_livestream=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    pass


@pytest.fixture
def blink():
    instance = MagicMock()
    instance.available = True
    instance.cameras = {"Test camera": fake_camera()}
    instance.sync = {}
    instance.start = AsyncMock(return_value=True)
    instance.refresh = AsyncMock()
    instance.get_homescreen = AsyncMock()
    instance.homescreen = {}
    with (
        patch("custom_components.blink_plus.coordinator.Blink", return_value=instance),
        patch("custom_components.blink_plus.config_flow.Blink", return_value=instance),
    ):
        yield instance


@pytest.fixture
def account(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="test@example.com",
        unique_id="test@example.com",
        data={"username": "test@example.com", "token": "not-real"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_creates_supported_entities_only(hass, account, blink):
    assert await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("camera.test_camera") is not None
    assert hass.states.get("binary_sensor.test_camera_motion").state == "off"
    assert not any(
        s.entity_id.startswith("sensor.test_camera_temperature")
        for s in hass.states.async_all()
    )
    camera = blink.cameras["Test camera"]
    camera.init_livestream.assert_not_awaited()
    assert await hass.config_entries.async_unload(account.entry_id)


async def test_cached_image_does_not_start_camera(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    from homeassistant.components.camera import async_get_image

    image = await async_get_image(hass, "camera.test_camera")
    assert image.content == b"cached-jpeg"
    blink.cameras["Test camera"].init_livestream.assert_not_awaited()
    await hass.config_entries.async_unload(account.entry_id)


async def test_options_bounds_and_preservation(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    result = await hass.config_entries.options.async_init(account.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "scan_interval": 120,
            "max_live_seconds": 60,
            "reconnect_cooldown": 15,
            "pan_step": 5,
            "tilt_step": 5,
            "live_enabled": False,
            "invert_pan": False,
            "invert_tilt": False,
            "pan_tilt_cameras": [],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert account.options["scan_interval"] == 120
    assert account.options["live_enabled"] is False
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(account.entry_id)


async def test_token_data_strips_secrets(hass):
    from custom_components.blink_plus.coordinator import token_data

    assert token_data(
        SimpleNamespace(
            login_attributes={
                "username": "a",
                "token": "b",
                "password": "c",
                "pin": "d",
            }
        )
    ) == {"username": "a", "token": "b"}


async def test_flow_does_not_store_password(hass, blink):
    auth = MagicMock(
        login_attributes={
            "username": "test@example.com",
            "token": "fake",
            "password": "secret",
        }
    )
    with patch("custom_components.blink_plus.config_flow.Auth", return_value=auth):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"username": "test@example.com", "password": "secret"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "password" not in result["data"]
    await hass.async_block_till_done()


async def test_mfa_flow(hass, blink):
    from blinkpy.auth import BlinkTwoFARequiredError

    blink.start.side_effect = BlinkTwoFARequiredError
    blink.send_2fa_code = AsyncMock(return_value=True)
    auth = MagicMock(login_attributes={"username": "test@example.com", "token": "fake"})
    with patch("custom_components.blink_plus.config_flow.Auth", return_value=auth):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"username": "test@example.com", "password": "secret"},
        )
        assert result["step_id"] == "mfa"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"pin": "123456"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "pin" not in result["data"]
    await hass.async_block_till_done()


async def test_token_refresh_does_not_reload(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    coordinator = account.runtime_data
    coordinator.api.auth = SimpleNamespace(
        login_attributes={"username": "test@example.com", "token": "refreshed"}
    )
    coordinator.save_tokens()
    await hass.async_block_till_done()
    assert account.data["token"] == "refreshed"
    assert account.runtime_data is coordinator
    await hass.config_entries.async_unload(account.entry_id)


async def test_option_change_reloads(hass, account, blink):
    await hass.config_entries.async_setup(account.entry_id)
    await hass.async_block_till_done()
    coordinator = account.runtime_data
    hass.config_entries.async_update_entry(account, options={"scan_interval": 120})
    await hass.async_block_till_done()
    assert account.runtime_data is not coordinator
    assert account.runtime_data.options["scan_interval"] == 120
    await hass.config_entries.async_unload(account.entry_id)
