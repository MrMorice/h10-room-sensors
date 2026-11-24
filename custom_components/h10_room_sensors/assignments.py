"""Persist and apply desired H10 bindings independently of the dialog lifetime."""

import asyncio
import logging
from datetime import timedelta
from time import monotonic

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .zigbee import DOMAIN, RADIO_ERRORS, change_binding, devices, room_temperature

_LOGGER = logging.getLogger(__name__)
LINK_PREFIX = "homeassistant://config/devices/device/"
LINK_QUERY = "?h10_room_sensors=1"
RETRY_INTERVAL = 20


def pending(row):
    return row["applied"] != row["desired"] or row.get("rebind", False)


class SensorListener:
    """Retry a pending operation when zigpy sees a packet from its sensor."""

    def __init__(self, manager, address):
        self.manager = manager
        self.address = address

    def device_last_seen_updated(self, timestamp):
        self.manager.sensor_seen(self.address)


class Assignments:
    """Store assignments and reconcile them with the sensor binding tables."""

    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, DOMAIN)
        self.rows = {}
        self.imported = set()
        self.active = set()
        self.last_attempt = {}
        self.listeners = {}
        self.entries = set()
        self.lock = asyncio.Lock()
        self.worker = None
        self.unsubs = []

    async def load(self):
        saved = await self.store.async_load() or {}
        self.rows = saved.get("rows", {})
        self.imported = set(saved.get("imported", []))

    async def persist(self):
        await self.store.async_save(
            {"rows": self.rows, "imported": sorted(self.imported)}
        )

    async def import_entry(self, entry):
        """Adopt a 0.1 assignment without touching its existing radio binding."""
        if "circuit" not in entry.data or entry.entry_id in self.imported:
            return
        async with self.lock:
            key = f"{entry.data['h10']}/{entry.data['circuit']}"
            if not entry.options.get("detached"):
                source = {
                    "address": entry.data["sensor"],
                    "endpoint": entry.data["endpoint"],
                }
                self.rows.setdefault(
                    key, {"applied": source, "desired": source, "error": None}
                )
            self.imported.add(entry.entry_id)
            await self.persist()

    @callback
    def start(self):
        self.unsubs.extend(
            (
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, self.refresh
                ),
                self.hass.bus.async_listen(
                    dr.EVENT_DEVICE_REGISTRY_UPDATED, self.refresh
                ),
                async_track_time_interval(
                    self.hass, self.refresh, timedelta(seconds=RETRY_INTERVAL)
                ),
            )
        )
        self.refresh()

    @callback
    def refresh(self, event=None):
        if not self.entries:
            return
        controllers, sensors = devices(self.hass)
        registry = dr.async_get(self.hass)
        for controller in controllers.values():
            device = registry.async_get(controller.registry_id)
            if device is None:
                continue
            link = f"{LINK_PREFIX}{device.id}{LINK_QUERY}"
            if device.configuration_url is None:
                registry.async_update_device(device.id, configuration_url=link)

        needed = {
            source["address"]
            for row in self.rows.values()
            if pending(row) and row["error"] != "rejected"
            for source in (row["applied"], row["desired"])
            if source is not None
        }
        for address, (device, listener) in tuple(self.listeners.items()):
            if (
                address not in needed
                or address not in sensors
                or sensors[address].zigpy_device is not device
            ):
                device.remove_listener(listener)
                del self.listeners[address]
        for address in (needed & sensors.keys()) - self.listeners.keys():
            device = sensors[address].zigpy_device
            listener = SensorListener(self, address)
            device.add_listener(listener)
            self.listeners[address] = (device, listener)
        self.kick()

    async def stop(self):
        if self.worker is not None:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        for unsub in self.unsubs:
            unsub()
        self.unsubs.clear()
        for device, listener in self.listeners.values():
            device.remove_listener(listener)
        self.listeners.clear()
        registry = dr.async_get(self.hass)
        for device in tuple(registry.devices.values()):
            if device.configuration_url == f"{LINK_PREFIX}{device.id}{LINK_QUERY}":
                registry.async_update_device(device.id, configuration_url=None)

    def controller(self, device_id):
        controllers, sensors = devices(self.hass)
        for address, controller in controllers.items():
            if controller.registry_id == device_id:
                return address, controller, sensors
        raise HomeAssistantError("Der ausgewählte H10 ist in ZHA nicht verfügbar.")

    def snapshot(self, device_id):
        address, h10, sensors = self.controller(device_id)
        circuits = []
        for circuit in h10.endpoints:
            key = f"{address}/{circuit}"
            row = self.rows.get(key, {"applied": None, "desired": None, "error": None})
            applied = row["applied"]["address"] if row["applied"] else None
            desired = row["desired"]["address"] if row["desired"] else None
            circuits.append(
                {
                    "circuit": circuit,
                    "applied": applied,
                    "sensor": desired,
                    "pending": pending(row),
                    "busy": key in self.active,
                    "error": row["error"],
                }
            )
        return {
            "device_id": device_id,
            "name": h10.name,
            "circuits": circuits,
            "sensors": dict(
                sorted(
                    ((key, sensor.name) for key, sensor in sensors.items()),
                    key=lambda item: item[1].casefold(),
                )
            ),
        }

    async def save(self, device_id, changes):
        """Validate a batch, then enqueue it before doing any radio work."""
        async with self.lock:
            address, h10, sensors = self.controller(device_id)
            updates = {}
            for change in changes:
                circuit = change["circuit"]
                target = change["sensor"]
                expected = change["expected"]
                key = f"{address}/{circuit}"
                row = self.rows.get(
                    key, {"applied": None, "desired": None, "error": None}
                )
                previous = row["desired"]["address"] if row["desired"] else None
                if circuit not in h10.endpoints or (
                    target is not None and target not in sensors
                ):
                    raise HomeAssistantError(
                        "Heizkreis oder Raumfühler ist nicht verfügbar."
                    )
                if key in updates:
                    raise HomeAssistantError(
                        "Jeder Heizkreis kann einmal pro Speichervorgang geändert werden."
                    )
                if previous != expected or key in self.active:
                    raise HomeAssistantError(
                        "Diese Zuordnung hat sich geändert oder wird gerade bearbeitet."
                    )
                source = (
                    {"address": target, "endpoint": sensors[target].endpoints[0]}
                    if target
                    else None
                )
                updates[key] = {
                    **row,
                    "desired": source,
                    "error": None,
                    "rebind": source is not None
                    and source == row["applied"]
                    and target == expected,
                }
            initial = self.rows.copy()
            self.rows.update(updates)
            try:
                await self.persist()
            except BaseException:
                self.rows = initial
                raise
            for key in updates:
                self.last_attempt.pop(key, None)
        self.refresh()
        return self.snapshot(device_id)

    async def temperature(self, device_id, circuit):
        _, controller, _ = self.controller(device_id)
        if circuit not in controller.endpoints:
            raise HomeAssistantError("Dieser Heizkreis ist nicht verfügbar.")
        return await room_temperature(controller.zigpy_device, circuit)

    @callback
    def sensor_seen(self, address):
        for key, last_attempt in tuple(self.last_attempt.items()):
            row = self.rows[key]
            source = row["applied"] or row["desired"]
            if (
                source
                and source["address"] == address
                and monotonic() - last_attempt > 3
            ):
                self.last_attempt.pop(key)
        self.kick()

    @callback
    def kick(self):
        if not self.entries or self.worker is not None:
            return
        if not any(
            pending(row) and row["error"] != "rejected" for row in self.rows.values()
        ):
            return
        self.worker = self.hass.async_create_background_task(
            self.apply(), "H10 room sensor bindings"
        )

    async def apply(self):
        try:
            controllers, sensors = devices(self.hass)
            unavailable = set()
            for key in tuple(self.rows):
                async with self.lock:
                    row = self.rows[key]
                    if not pending(row) or row["error"] == "rejected":
                        continue
                    if (
                        monotonic() - self.last_attempt.get(key, -RETRY_INTERVAL)
                        < RETRY_INTERVAL
                    ):
                        continue
                    address, circuit_text = key.split("/")
                    controller = controllers.get(address)
                    circuit = int(circuit_text)
                    source = row["applied"] or row["desired"]
                    sensor = sensors.get(source["address"])
                    if (
                        not controller
                        or circuit not in controller.endpoints
                        or not sensor
                        or source["address"] in unavailable
                    ):
                        continue
                    self.active.add(key)
                try:
                    await self.apply_row(key, row, controller, circuit, sensors)
                except RADIO_ERRORS:
                    current_source = row["applied"] or row["desired"]
                    unavailable.add(current_source["address"])
                    self.last_attempt[key] = monotonic()
                except HomeAssistantError as err:
                    _LOGGER.warning("Could not apply room sensor to %s: %s", key, err)
                    async with self.lock:
                        row["error"] = "rejected"
                        await self.persist()
                finally:
                    self.active.discard(key)
                    if not pending(row):
                        self.last_attempt.pop(key, None)
        finally:
            self.worker = None

    async def apply_row(self, key, row, controller, circuit, sensors):
        # Disconnect first so the H10 never alternates between two room sensors.
        # Persist that transition so a sleeping replacement can be retried safely.
        while pending(row):
            connect = row["applied"] is None or row.get("rebind", False)
            source = row["desired"] if connect else row["applied"]
            sensor = sensors.get(source["address"])
            if sensor is None:
                return
            await change_binding(
                sensor.zigpy_device,
                source["endpoint"],
                controller.zigpy_device,
                circuit,
                connect=connect,
            )
            async with self.lock:
                assert self.rows[key] is row
                row["applied"] = source if connect else None
                row["rebind"] = False
                await self.persist()
