from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from custom_components.h10_room_sensors import assignments, zigbee
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from zigpy.types import EUI64
from zigpy.zdo.types import Status

H10 = "00:11:22:33:44:55:66:77"
SHELLY = "00:11:22:33:44:55:66:88"
OTHER = "00:11:22:33:44:55:66:99"


def setup(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    manager = assignments.Assignments(hass)
    manager.store = SimpleNamespace(async_save=AsyncMock())
    controller = zigbee.Device(
        "H10", SimpleNamespace(ieee=EUI64.convert(H10)), (1, 2), "h10"
    )
    sensors = {
        address: zigbee.Device(
            name,
            SimpleNamespace(
                ieee=EUI64.convert(address),
                zdo=SimpleNamespace(
                    Bind_req=AsyncMock(return_value=[Status.SUCCESS]),
                    Unbind_req=AsyncMock(return_value=[Status.NO_ENTRY]),
                ),
            ),
            (3,),
        )
        for address, name in ((SHELLY, "Wohnzimmer"), (OTHER, "Küche"))
    }
    return manager, {H10: controller}, sensors


def change(circuit, target, previous=None):
    return {"circuit": circuit, "sensor": target, "expected": previous}


def legacy():
    return SimpleNamespace(
        entry_id="existing",
        data={"h10": H10, "circuit": 1, "sensor": SHELLY, "endpoint": 3},
        options={},
    )


@pytest.mark.asyncio
async def test_import_and_assign_same_sensor_to_multiple_circuits(tmp_path):
    manager, controllers, sensors = setup(tmp_path)
    radio = sensors[SHELLY].zigpy_device.zdo
    with patch.object(assignments, "devices", return_value=(controllers, sensors)):
        await manager.import_entry(legacy())
        assert manager.snapshot("h10")["circuits"][0]["applied"] == SHELLY
        radio.Bind_req.assert_not_awaited()
        state = await manager.save("h10", [change(2, SHELLY)])
        assert [row["sensor"] for row in state["circuits"]] == [SHELLY, SHELLY]
        assert [row["pending"] for row in state["circuits"]] == [False, True]
        await manager.apply()
        assert [row["pending"] for row in manager.snapshot("h10")["circuits"]] == [
            False,
            False,
        ]

    source, endpoint, cluster, target = radio.Bind_req.await_args.args
    assert (source, endpoint, cluster) == (EUI64.convert(SHELLY), 3, 0x0402)
    assert (target.ieee, target.endpoint) == (EUI64.convert(H10), 2)
    radio.Unbind_req.assert_not_awaited()


@pytest.mark.asyncio
async def test_replacement_unbinds_before_retrying_sleeping_sensor(tmp_path):
    manager, controllers, sensors = setup(tmp_path)
    old = sensors[SHELLY].zigpy_device.zdo
    new = sensors[OTHER].zigpy_device.zdo
    new.Bind_req.side_effect = [TimeoutError, [Status.SUCCESS]]

    with patch.object(assignments, "devices", return_value=(controllers, sensors)):
        await manager.import_entry(legacy())
        await manager.save("h10", [change(1, OTHER, SHELLY)])
        await manager.apply()
        assert manager.rows[f"{H10}/1"]["applied"] is None
        assert manager.snapshot("h10")["circuits"][0]["pending"]
        old.Unbind_req.assert_awaited_once()

        manager.last_attempt.clear()
        await manager.apply()
        assert manager.snapshot("h10")["circuits"][0]["applied"] == OTHER
        assert new.Bind_req.await_count == 2
        old.Unbind_req.assert_awaited_once()

        await manager.save("h10", [change(1, None, OTHER)])
        await manager.apply()
        await manager.import_entry(legacy())
        assert manager.snapshot("h10")["circuits"][0]["applied"] is None


@pytest.mark.asyncio
async def test_batch_validation_rejects_conflicts_without_saving(tmp_path):
    manager, controllers, sensors = setup(tmp_path)
    with patch.object(assignments, "devices", return_value=(controllers, sensors)):
        await manager.import_entry(legacy())
        manager.store.async_save.reset_mock()
        with pytest.raises(HomeAssistantError):
            await manager.save("h10", [change(2, SHELLY), change(1, OTHER, None)])
        assert not manager.snapshot("h10")["circuits"][1]["pending"]
        manager.store.async_save.assert_not_awaited()
