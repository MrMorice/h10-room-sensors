"""Find compatible ZHA devices and manage their direct bindings."""

from dataclasses import dataclass

from homeassistant.components.zha.helpers import get_zha_gateway
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from zigpy.exceptions import ZigbeeException
from zigpy.zdo import types as zdo

DOMAIN = "h10_room_sensors"
TEMPERATURE = 0x0402
THERMOSTAT = 0x0201
CIRCUITS = range(1, 11)
RADIO_ERRORS = (TimeoutError, ZigbeeException)


@dataclass(frozen=True)
class Device:
    """A paired device with its display name and compatible endpoints."""

    name: str
    zigpy_device: object
    endpoints: tuple[int, ...]
    registry_id: str | None = None


def devices(hass):
    """Return compatible H10s and temperature sensors keyed by stable IEEE address."""
    controllers = {}
    sensors = {}
    try:
        app = get_zha_gateway(hass).application_controller
    except (HomeAssistantError, KeyError, ValueError):
        return controllers, sensors

    registry = dr.async_get(hass)
    for ieee, device in app.devices.items():
        if device.nwk == 0:
            continue
        address = str(ieee)
        entry = registry.async_get_device(identifiers={("zha", address)})
        if entry is None or entry.disabled_by is not None:
            continue
        name = entry.name_by_user or entry.name or device.model or address
        if (device.manufacturer or "").casefold() == "ubisys" and device.model == "H10":
            endpoints = tuple(
                number
                for number in CIRCUITS
                if (ep := device.endpoints.get(number)) is not None
                and THERMOSTAT in ep.in_clusters
                and TEMPERATURE in ep.out_clusters
            )
            if endpoints:
                controllers[address] = Device(name, device, endpoints, entry.id)
            continue

        endpoints = tuple(
            number
            for number, endpoint in device.endpoints.items()
            if number != 0 and TEMPERATURE in endpoint.in_clusters
        )
        # This flow is for room sensors with one unambiguous reporting endpoint.
        if len(endpoints) == 1:
            sensors[address] = Device(name, device, endpoints, entry.id)

    return controllers, sensors


def _destination(h10, circuit):
    address = zdo.MultiAddress()
    address.addrmode = 3
    address.ieee = h10.ieee
    address.endpoint = circuit
    return address


async def change_binding(sensor, endpoint, h10, circuit, *, connect):
    """Set or clear exactly one temperature binding on the source sensor."""
    request = sensor.zdo.Bind_req if connect else sensor.zdo.Unbind_req
    (status, *_) = await request(
        sensor.ieee, endpoint, TEMPERATURE, _destination(h10, circuit)
    )
    if status != zdo.Status.SUCCESS and (connect or status != zdo.Status.NO_ENTRY):
        raise HomeAssistantError(f"Zigbee returned {status!s}")


async def room_temperature(h10, circuit):
    """Read the H10's current room temperature from the thermostat itself."""
    cluster = h10.endpoints[circuit].in_clusters[THERMOSTAT]
    values, _ = await cluster.read_attributes(["local_temperature"], allow_cache=False)
    value = values.get("local_temperature")
    if value is None or value == -32768:
        return None
    return value / 100


async def binding_page(sensor, index):
    """Read one page of the binding table without changing the device."""
    status, *payload = await sensor.zdo.Mgmt_Bind_req(index)
    if status != zdo.Status.SUCCESS:
        raise HomeAssistantError(
            f"Der Fühler konnte die Binding-Tabelle nicht lesen ({status!s})."
        )
    if len(payload) != 3:
        raise HomeAssistantError(
            "Der Fühler hat eine unvollständige Binding-Tabelle gemeldet."
        )

    total, start, bindings = payload
    if (
        start != index
        or start + len(bindings) > total
        or (start < total and not bindings)
    ):
        raise HomeAssistantError(
            "Der Fühler hat einen ungültigen Ausschnitt der Binding-Tabelle gemeldet."
        )

    records = []
    for binding in bindings:
        target = binding.DstAddress
        record = {
            "source_ieee": str(binding.SrcAddress),
            "source_endpoint": int(binding.SrcEndpoint),
            "cluster": int(binding.ClusterId),
            "address_mode": int(target.addrmode),
        }
        if target.addrmode == 3:
            record.update(
                target_ieee=str(target.ieee), target_endpoint=int(target.endpoint)
            )
        elif target.addrmode == 1:
            record["group"] = int(target.nwk)
        records.append(record)
    following = start + len(records)
    return {
        "total": int(total),
        "start_index": int(start),
        "next_index": following if following < total else None,
        "bindings": records,
    }
