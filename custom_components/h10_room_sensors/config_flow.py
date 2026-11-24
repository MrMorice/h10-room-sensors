"""Activate room-sensor management on the existing H10 device pages."""

from homeassistant import config_entries

from .zigbee import DOMAIN


class H10RoomSensorsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Enable the device dialog once for the Home Assistant installation."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="H10 Room Sensors", data={})
        return self.async_show_form(step_id="user")
