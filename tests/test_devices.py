"""Tests for the device abstraction layer.

GPIO is always mocked — no Raspberry Pi required to run these tests.
"""

import pytest
from devices.gpio_device import GPIODevice


@pytest.fixture
def light_device():
    """GPIODevice instance using a safe test pin (mocked GPIO)."""
    return GPIODevice(name="Test Light", gpio_pin=99)


@pytest.mark.asyncio
class TestGPIODevice:
    """Tests for ``GPIODevice``."""

    async def test_initial_status_is_off(self, light_device):
        """Newly created device reports 'off' status."""
        status = await light_device.status()
        assert status == "off"

    async def test_turn_on(self, light_device):
        """Turning on a device returns True and updates status."""
        result = await light_device.on()
        assert result is True
        assert await light_device.status() == "on"

    async def test_turn_off(self, light_device):
        """Turning off a device returns True and updates status."""
        await light_device.on()
        result = await light_device.off()
        assert result is True
        assert await light_device.status() == "off"

    async def test_toggle_on_off(self, light_device):
        """Device can be toggled on and off multiple times."""
        await light_device.on()
        assert await light_device.status() == "on"
        await light_device.off()
        assert await light_device.status() == "off"
        await light_device.on()
        assert await light_device.status() == "on"

    def test_device_name(self, light_device):
        """Device name is accessible via the name property."""
        assert light_device.name == "Test Light"

    def test_repr(self, light_device):
        """Device repr includes class name and device name."""
        r = repr(light_device)
        assert "GPIODevice" in r
        assert "Test Light" in r
