from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.h10_room_sensors import config_flow, zigbee
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from zigpy.types import EUI64
from zigpy.zdo.types import Binding, MultiAddress, Status

H10 = "00:11:22:33:44:55:66:77"
SHELLY = "00:11:22:33:44:55:66:88"


def fake_devices():
    controller = SimpleNamespace(
        ieee=EUI64.convert(H10),
        endpoints={
            1: SimpleNamespace(
                in_clusters={
                    zigbee.THERMOSTAT: SimpleNamespace(
                        read_attributes=AsyncMock(
                            return_value=({"local_temperature": 2195}, {})
                        )
                    ),
                },
            ),
        },
    )
    sensor = SimpleNamespace(
        ieee=EUI64.convert(SHELLY),
        zdo=SimpleNamespace(
            Bind_req=AsyncMock(return_value=[Status.SUCCESS]),
            Unbind_req=AsyncMock(return_value=[Status.NO_ENTRY]),
            Mgmt_Bind_req=AsyncMock(),
        ),
    )
    return {H10: zigbee.Device("H10", controller, (1, 2))}, {
        SHELLY: zigbee.Device("Wohnzimmer", sensor, (3,))
    }


def configured_devices(controllers, sensors):
    return patch.object(config_flow, "devices", return_value=(controllers, sensors))


@pytest.mark.asyncio
async def test_assign_retries_after_sleep_and_targets_exact_circuit(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    flow = config_flow.H10RoomSensorsConfigFlow()
    flow.hass = hass
    flow.handler = zigbee.DOMAIN
    flow.flow_id = "setup"
    flow.context = {"source": config_entries.SOURCE_USER}

    controllers, sensors = fake_devices()
    radio = sensors[SHELLY].zigpy_device.zdo
    radio.Bind_req.side_effect = [TimeoutError, [Status.SUCCESS]]

    with configured_devices(controllers, sensors):
        hardware = await flow.async_step_user()
        assert hardware["data_schema"]({"h10": H10}) == {"h10": H10}
        assignment = await flow.async_step_user({"h10": H10})
        selection = assignment["data_schema"]({"circuit": "1", "sensor": SHELLY})
        retry = await flow.async_step_assign(selection)
        assert retry["errors"] == {"base": "no_response"}
        result = await flow.async_step_assign(selection)

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {"h10": H10, "circuit": 1, "sensor": SHELLY, "endpoint": 3}
    source, endpoint, cluster, target = radio.Bind_req.await_args.args
    assert (source, endpoint, cluster) == (EUI64.convert(SHELLY), 3, 0x0402)
    assert (target.addrmode, target.ieee, target.endpoint) == (3, EUI64.convert(H10), 1)


@pytest.mark.asyncio
async def test_check_reads_h10_and_only_confirms_matching_entry(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    flow = config_flow.CircuitOptionsFlow()
    flow.hass = hass
    flow.flow_id = "check"
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    entry = config_entries.ConfigEntry(
        data={"h10": H10, "circuit": 1, "sensor": SHELLY, "endpoint": 3},
        discovery_keys=MappingProxyType({}),
        domain=zigbee.DOMAIN,
        minor_version=1,
        options={},
        source=config_entries.SOURCE_USER,
        subentries_data=None,
        title="H10 · 1 · Wohnzimmer",
        unique_id=f"{H10}/1",
        version=1,
    )
    hass.config_entries._entries[entry.entry_id] = entry
    flow.handler = entry.entry_id
    controllers, sensors = fake_devices()
    radio = sensors[SHELLY].zigpy_device.zdo

    def binding(circuit):
        return Binding(
            SrcAddress=EUI64.convert(SHELLY),
            SrcEndpoint=3,
            ClusterId=0x0402,
            DstAddress=MultiAddress(
                addrmode=3, ieee=EUI64.convert(H10), endpoint=circuit
            ),
        )

    radio.Mgmt_Bind_req.side_effect = [
        [Status.SUCCESS, 1, 0, [binding(2)]],
        [Status.SUCCESS, 2, 0, [binding(2)]],
        [Status.SUCCESS, 2, 1, [binding(1)]],
    ]

    with configured_devices(controllers, sensors):
        assert (await flow.async_step_init())[
            "type"
        ] == data_entry_flow.FlowResultType.MENU
        assert (await flow.async_step_check())["step_id"] == "check"
        missing = await flow.async_step_check({})
        assert missing["errors"] == {"base": "binding_missing"}
        found = await flow.async_step_check({})
        assert found["errors"] == {}
        assert found["description_placeholders"]["temperature"] == "21.95 °C"
        detached = await flow.async_step_detach({})
        assert detached["data"] == {"detached": True}
