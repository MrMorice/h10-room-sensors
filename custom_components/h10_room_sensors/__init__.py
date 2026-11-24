"""Manage direct room-temperature bindings for ubisys H10 controllers."""

from .assignments import Assignments
from .coordinator_test import CoordinatorTest
from .panel import register
from .zigbee import DOMAIN


async def async_setup(hass, config):
    """Register the dialog, then load the durable assignment state."""
    manager = Assignments(hass)
    await manager.load()
    await register(hass)
    hass.data[DOMAIN] = manager
    manager.coordinator_test = CoordinatorTest(hass)
    await manager.coordinator_test.recover()
    return True


async def async_setup_entry(hass, entry):
    """Activate the device-page links and adopt existing assignments."""
    manager = hass.data[DOMAIN]
    await manager.import_entry(entry)
    manager.entries.add(entry.entry_id)
    if not manager.unsubs:
        manager.start()
    else:
        manager.refresh()
    return True


async def async_unload_entry(hass, entry):
    """Remove the device-page links when the integration is deactivated."""
    manager = hass.data[DOMAIN]
    manager.entries.discard(entry.entry_id)
    if not manager.entries:
        await manager.stop()
    return True
