"""Device dialog assets and admin-only WebSocket commands."""

from pathlib import Path

import probatio as vol
from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.exceptions import HomeAssistantError

from .zigbee import DOMAIN, RADIO_ERRORS, binding_page

ASSET = "/h10_room_sensors_static/device-dialog.js"


async def register(hass):
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                ASSET, str(Path(__file__).with_name("device-dialog.js")), False
            )
        ]
    )
    frontend.add_extra_js_url(hass, f"{ASSET}?v=0.2.2")
    for handler in (
        get_settings,
        save_settings,
        get_temperature,
        get_bindings,
        remove_stale_binding,
        start_coordinator_test,
        coordinator_test_status,
    ):
        websocket_api.async_register_command(hass, handler)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/device/info", vol.Required("device_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def get_settings(hass, connection, msg):
    try:
        result = hass.data[DOMAIN].snapshot(msg["device_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/device/save",
        vol.Required("device_id"): str,
        vol.Required("changes"): vol.All(
            [
                {
                    vol.Required("circuit"): int,
                    vol.Required("sensor"): vol.Any(None, str),
                    vol.Required("expected"): vol.Any(None, str),
                }
            ],
            vol.Length(min=1, max=10),
        ),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def save_settings(hass, connection, msg):
    try:
        result = await hass.data[DOMAIN].save(msg["device_id"], msg["changes"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "assignment_error", str(err))
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/device/temperature",
        vol.Required("device_id"): str,
        vol.Required("circuit"): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def get_temperature(hass, connection, msg):
    try:
        value = await hass.data[DOMAIN].temperature(msg["device_id"], msg["circuit"])
    except RADIO_ERRORS:
        connection.send_error(
            msg["id"], "no_response", "Der H10 antwortet gerade nicht."
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
    else:
        connection.send_result(msg["id"], value)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/device/bindings",
        vol.Required("device_id"): str,
        vol.Required("sensor"): str,
        vol.Optional("start_index", default=0): vol.All(int, vol.Range(min=0, max=255)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def get_bindings(hass, connection, msg):
    try:
        address, _, sensors = hass.data[DOMAIN].controller(msg["device_id"])
        sensor = sensors.get(msg["sensor"])
        if sensor is None:
            raise HomeAssistantError("Dieser Raumfühler ist in ZHA nicht verfügbar.")

        device = sensor.zigpy_device
        page = await binding_page(device, msg["start_index"])
        coordinator = str(device.application.state.node_info.ieee)
        connection.send_result(
            msg["id"],
            {
                **page,
                "sensor": msg["sensor"],
                "sensor_endpoint": sensor.endpoints[0],
                "h10_ieee": address,
                "coordinator_ieee": coordinator,
            },
        )
    except RADIO_ERRORS:
        connection.send_error(
            msg["id"],
            "no_response",
            "Der Raumfühler antwortet gerade nicht. Wecke ihn und versuche es erneut.",
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "binding_table_error", str(err))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/device/remove_stale_binding",
        vol.Required("device_id"): str,
        vol.Required("sensor"): str,
        vol.Required("circuit"): int,
        vol.Required("expected"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def remove_stale_binding(hass, connection, msg):
    try:
        await hass.data[DOMAIN].remove_stale_binding(
            msg["device_id"], msg["circuit"], msg["sensor"], msg["expected"]
        )
    except RADIO_ERRORS:
        connection.send_error(
            msg["id"], "no_response", "Der Raumfühler antwortet gerade nicht."
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "binding_cleanup_error", str(err))
    else:
        connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/device/coordinator_test",
        vol.Required("device_id"): str,
        vol.Required("sensor"): str,
        vol.Required("circuit"): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def start_coordinator_test(hass, connection, msg):
    test = hass.data[DOMAIN].coordinator_test
    try:
        result = test.start(msg["device_id"], msg["sensor"], msg["circuit"])
    except HomeAssistantError as exc:
        connection.send_error(msg["id"], "test_error", str(exc))
    else:
        connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/device/coordinator_test/status"}
)
@websocket_api.require_admin
@websocket_api.async_response
async def coordinator_test_status(hass, connection, msg):
    connection.send_result(msg["id"], hass.data[DOMAIN].coordinator_test.result)
