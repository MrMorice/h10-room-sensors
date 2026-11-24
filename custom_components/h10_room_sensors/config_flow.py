"""Home Assistant setup and options for assigning a room sensor to a heating circuit."""

import asyncio

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .zigbee import (
    DOMAIN,
    RADIO_ERRORS,
    change_binding,
    devices,
    has_binding,
    room_temperature,
)


def dropdown(options):
    return selector.SelectSelector({"options": options, "mode": "dropdown"})


def device_options(items):
    return [
        {"value": address, "label": device.name}
        for address, device in sorted(
            items.items(), key=lambda item: item[1].name.casefold()
        )
    ]


class H10RoomSensorsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Select the H10, then assign a sensor to one of its circuits."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        controllers, sensors = devices(self.hass)
        if not controllers:
            return self.async_abort(reason="no_h10")
        if not sensors:
            return self.async_abort(reason="no_sensors")
        if user_input is not None and user_input["h10"] in controllers:
            self.h10_address = user_input["h10"]
            return await self.async_step_assign()
        return self.async_show_form(
            step_id="user",
            errors={"base": "device_missing"} if user_input is not None else {},
            data_schema=vol.Schema(
                {vol.Required("h10"): dropdown(device_options(controllers))}
            ),
        )

    async def async_step_assign(self, user_input=None):
        controllers, sensors = devices(self.hass)
        h10 = controllers.get(self.h10_address)
        if h10 is None:
            return self.async_abort(reason="no_h10")
        if not sensors:
            return self.async_abort(reason="no_sensors")

        used = {entry.unique_id for entry in self._async_current_entries()}
        free = [
            str(circuit)
            for circuit in h10.endpoints
            if f"{self.h10_address}/{circuit}" not in used
        ]
        if not free:
            return self.async_abort(reason="no_free_circuits")

        errors = {}
        if user_input is not None:
            sensor_address = user_input["sensor"]
            sensor = sensors.get(sensor_address)
            circuit = int(user_input["circuit"])
            if sensor is None or str(circuit) not in free:
                errors["base"] = "device_missing"
            else:
                await self.async_set_unique_id(f"{self.h10_address}/{circuit}")
                self._abort_if_unique_id_configured()
                try:
                    await change_binding(
                        sensor.zigpy_device,
                        sensor.endpoints[0],
                        h10.zigpy_device,
                        circuit,
                        connect=True,
                    )
                except RADIO_ERRORS:
                    errors["base"] = "no_response"
                except HomeAssistantError:
                    errors["base"] = "binding_rejected"
                else:
                    return self.async_create_entry(
                        title=f"{h10.name} · {circuit} · {sensor.name}",
                        data={
                            "h10": self.h10_address,
                            "circuit": circuit,
                            "sensor": sensor_address,
                            "endpoint": sensor.endpoints[0],
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(
                    "circuit", default="1" if "1" in free else free[0]
                ): dropdown(free),
                vol.Required("sensor"): dropdown(device_options(sensors)),
            }
        )
        return self.async_show_form(
            step_id="assign",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            description_placeholders={"h10": h10.name},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CircuitOptionsFlow()


class CircuitOptionsFlow(config_entries.OptionsFlow):
    """Check, restore, or remove an existing assignment."""

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=(
                ["check", "restore"]
                if self.config_entry.options.get("detached")
                else ["check", "restore", "detach"]
            ),
            description_placeholders={"assignment": self.config_entry.title},
        )

    async def async_step_restore(self, user_input=None):
        return await self._manage("restore", user_input)

    async def async_step_detach(self, user_input=None):
        return await self._manage("detach", user_input)

    async def async_step_check(self, user_input=None):
        return await self._manage("check", user_input)

    async def _manage(self, step, user_input):
        data = self.config_entry.data
        controllers, sensors = devices(self.hass)
        h10 = controllers.get(data["h10"])
        sensor = sensors.get(data["sensor"])
        circuit = data["circuit"]
        endpoint = data["endpoint"]
        if (
            h10 is None
            or sensor is None
            or circuit not in h10.endpoints
            or endpoint not in sensor.endpoints
        ):
            return self.async_abort(reason="device_missing")

        error = None
        if user_input is not None:
            try:
                if step == "check":
                    bound, temperature = await asyncio.gather(
                        has_binding(
                            sensor.zigpy_device, endpoint, h10.zigpy_device, circuit
                        ),
                        room_temperature(h10.zigpy_device, circuit),
                    )
                    return self.async_show_form(
                        step_id="check_result",
                        description_placeholders={
                            "assignment": self.config_entry.title,
                            "temperature": "—"
                            if temperature is None
                            else f"{temperature:.2f} °C",
                        },
                        errors={} if bound else {"base": "binding_missing"},
                    )

                await change_binding(
                    sensor.zigpy_device,
                    endpoint,
                    h10.zigpy_device,
                    circuit,
                    connect=step == "restore",
                )
            except RADIO_ERRORS:
                error = "no_response"
            except HomeAssistantError:
                error = "binding_rejected"
            else:
                return self.async_create_entry(
                    title="", data={"detached": step == "detach"}
                )

        return self.async_show_form(
            step_id=step,
            description_placeholders={"assignment": self.config_entry.title},
            errors={"base": error} if error else {},
        )

    async def async_step_check_result(self, user_input=None):
        return self.async_abort(reason="check_complete")
