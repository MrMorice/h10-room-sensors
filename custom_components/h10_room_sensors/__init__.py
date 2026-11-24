"""Manage direct room-temperature bindings for ubisys H10 controllers."""


async def async_setup_entry(hass, entry):
    """Load an existing assignment without changing the Zigbee network."""
    return True


async def async_unload_entry(hass, entry):
    """Unload Home Assistant's entry."""
    return True
