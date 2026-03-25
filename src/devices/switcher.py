"""Switcher Touch direct LAN control via aioswitcher.

Talks to the device directly over TCP — no Homebridge, no cloud.

Config (.env):
    SWITCHER_DEVICE_IP   — device LAN IP (e.g. 192.168.68.51)
    SWITCHER_DEVICE_ID   — hex device ID (e.g. 066f21)
    SWITCHER_DEVICE_KEY  — device key from plugin logs (e.g. 15)
"""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)


def _cfg() -> tuple[str, str, str]:
    from config import Config
    return Config.SWITCHER_IP, Config.SWITCHER_ID, Config.SWITCHER_KEY


async def turn_on() -> None:
    """Turn the Switcher device on."""
    from aioswitcher.api import Command, SwitcherApi
    from aioswitcher.device import DeviceType

    ip, device_id, device_key = _cfg()
    logger.info(f"Switcher: turning ON (ip={ip})")
    async with SwitcherApi(DeviceType.TOUCH, ip, device_id, device_key) as api:
        resp = await api.control_device(Command.ON)
    logger.info(f"Switcher: turn_on response successful={resp.successful}")
    if not resp.successful:
        raise RuntimeError(f"Device rejected ON command (successful=False)")


async def turn_off() -> None:
    """Turn the Switcher device off."""
    from aioswitcher.api import Command, SwitcherApi
    from aioswitcher.device import DeviceType

    ip, device_id, device_key = _cfg()
    logger.info(f"Switcher: turning OFF (ip={ip})")
    async with SwitcherApi(DeviceType.TOUCH, ip, device_id, device_key) as api:
        resp = await api.control_device(Command.OFF)
    logger.info(f"Switcher: turn_off response successful={resp.successful}")
    if not resp.successful:
        raise RuntimeError(f"Device rejected OFF command (successful=False)")


async def get_state() -> dict:
    """Return current device state: {is_on: bool, power_w: int|None}."""
    from aioswitcher.api import SwitcherApi
    from aioswitcher.device import DeviceState, DeviceType

    ip, device_id, device_key = _cfg()
    logger.info(f"Switcher: getting state (ip={ip})")
    async with SwitcherApi(DeviceType.TOUCH, ip, device_id, device_key) as api:
        resp = await api.get_state()

    return {
        "is_on": resp.state == DeviceState.ON,
        "power_w": getattr(resp, "power_consumption", None),
    }
