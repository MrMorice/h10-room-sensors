"""Device dialog assets and admin-only WebSocket commands."""

from pathlib import Path

import probatio as vol
from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.exceptions import HomeAssistantError

from .zigbee import DOMAIN, RADIO_ERRORS

ASSET = "/h10_room_sensors_static/device-dialog.js"


async def register(hass):
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                ASSET, str(Path(__file__).with_name("device-dialog.js")), False
            )
        ]
    )
    frontend.add_extra_js_url(hass, f"{ASSET}?v=0.2.0")
    for handler in (get_settings, save_settings, get_temperature):
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
