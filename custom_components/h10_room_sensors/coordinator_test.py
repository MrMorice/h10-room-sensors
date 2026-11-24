"""Temporarily suspend one coordinator temperature binding and recover it."""

import asyncio
import logging
from time import monotonic

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .zigbee import (
    DOMAIN,
    RADIO_ERRORS,
    TEMPERATURE,
    binding_page,
    change_binding,
    devices,
)

_LOGGER = logging.getLogger(__name__)


class CoordinatorTest:
    """Run a bounded report test and durably track the binding to restore."""

    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, f"{DOMAIN}.coordinator_test")
        self.lock = asyncio.Lock()
        self.task = None
        self.result = {"phase": "idle"}

    async def recover(self):
        """Reinstate a binding if Home Assistant stopped during the test."""
        if saved := await self.store.async_load():
            self.task = self.hass.async_create_background_task(
                self.restore(saved), "Restore room sensor coordinator binding"
            )

    def update(self, phase, **fields):
        self.result = {**self.result, **fields, "phase": phase}

    def start(self, device_id, sensor_address, circuit):
        if self.task is not None and not self.task.done():
            raise HomeAssistantError("Ein Zigbee-Test läuft bereits.")
        manager = self.hass.data[DOMAIN]
        _, _, sensors = manager.controller(device_id)
        circuits = manager.snapshot(device_id)["circuits"]
        row = next(
            (row for row in circuits if row["circuit"] == circuit),
            None,
        )
        if (
            not row
            or row["applied"] != sensor_address
            or row["pending"]
            or sensor_address not in sensors
        ):
            raise HomeAssistantError(
                "Für den Test muss der Fühler dem Heizkreis bereits zugeordnet sein."
            )
        reference = next(
            (
                item["circuit"]
                for item in circuits
                if item["circuit"] != circuit
                and item["applied"] == sensor_address
                and not item["pending"]
            ),
            None,
        )
        self.result = {
            "phase": "reading_table",
            "circuit": circuit,
            "reference_circuit": reference,
        }
        self.task = self.hass.async_create_background_task(
            self.run(manager, device_id, sensors[sensor_address], circuit, reference),
            "Test room sensor without coordinator temperature binding",
        )
        return self.result

    async def run(self, manager, device_id, sensor, circuit, reference):
        device = sensor.zigpy_device
        address = str(device.ieee)
        coordinator = str(device.application.state.node_info.ieee)
        endpoint = sensor.endpoints[0]
        state = None
        try:
            initial = await manager.temperature(device_id, circuit)
            reference_initial = (
                await manager.temperature(device_id, reference) if reference else None
            )
            cursor = 0
            entries = []
            while cursor is not None:
                page = await binding_page(device, cursor)
                entries.extend(page["bindings"])
                cursor = page["next_index"]
            targets = [
                r["target_endpoint"]
                for r in entries
                if r["cluster"] == TEMPERATURE
                and r["source_ieee"] == address
                and r["source_endpoint"] == endpoint
                and r.get("target_ieee") == coordinator
            ]
            if len(targets) != 1:
                raise HomeAssistantError(
                    "Für den Test wird genau ein Temperatur-Binding zum Koordinator benötigt."
                )

            state = {
                "sensor": address,
                "source_endpoint": endpoint,
                "target_endpoint": targets[0],
                "coordinator": coordinator,
            }
            await self.store.async_save(state)
            self.update("disconnecting")
            await change_binding(
                device,
                endpoint,
                self.coordinator(device, coordinator),
                targets[0],
                connect=False,
            )
            self.update(
                "waiting_for_report",
                initial_temperature=initial,
                reference_initial=reference_initial,
            )

            # The H10 keeps regulating. Observe only its own room-temperature reading.
            deadline = monotonic() + 90
            while monotonic() < deadline:
                try:
                    value = await manager.temperature(device_id, circuit)
                except RADIO_ERRORS:
                    value = None
                if value is not None and value != initial:
                    self.result["measured_temperature"] = value
                    break
                if reference:
                    try:
                        other = await manager.temperature(device_id, reference)
                    except RADIO_ERRORS:
                        other = None
                    if other is not None and other != reference_initial:
                        self.result["reference_temperature"] = other
                await asyncio.sleep(3)
        except (*RADIO_ERRORS, HomeAssistantError) as exc:
            self.result["error"] = str(exc) or type(exc).__name__
        finally:
            if state is not None:
                await self.restore(state)
            else:
                self.update("failed")

    @staticmethod
    def coordinator(device, expected):
        app = device.application
        address = app.state.node_info.ieee
        if str(address) != expected:
            raise HomeAssistantError(
                "Der Zigbee-Koordinator hat sich seit dem Test geändert."
            )
        return app.get_device(ieee=address)

    async def restore(self, state):
        async with self.lock:
            self.update("restoring", restored=False)
            while True:
                _, sensors = devices(self.hass)
                if sensor := sensors.get(state["sensor"]):
                    try:
                        device = sensor.zigpy_device
                        await change_binding(
                            device,
                            state["source_endpoint"],
                            self.coordinator(device, state["coordinator"]),
                            state["target_endpoint"],
                            connect=True,
                        )
                    except (*RADIO_ERRORS, HomeAssistantError) as exc:
                        _LOGGER.warning(
                            "Waiting to restore coordinator temperature binding: %s",
                            exc,
                        )
                    else:
                        await self.store.async_remove()
                        self.update("complete", restored=True)
                        return
                await asyncio.sleep(5)
