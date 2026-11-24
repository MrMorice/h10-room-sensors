# H10 Room Sensors

Home Assistant configuration for direct Zigbee room-temperature reporting to
an ubisys H10. The thermostat on the H10 runs the control loop.

## Installation

On Home Assistant 2026.11 or later, add the public repository
`https://github.com/MrMorice/h10-room-sensors` under
**Settings → Marketplace → Add from link** and install **H10 Room Sensors**.
The Marketplace requires a connected GitHub account for custom repositories.

For a manual installation, copy `custom_components/h10_room_sensors` into the Home Assistant configuration
directory's `custom_components` folder and restart Home Assistant. The
integration uses the ZHA APIs from Home Assistant 2026.10. The H10 and room
sensor must already be paired with ZHA.

## Add a heating circuit

1. Open **Settings → Devices & services → Add integration → H10 Room Sensors**.
2. Select the H10, heating circuit and room sensor. Wake the sensor immediately
   before confirming. On a Shelly BLU H&T ZB, press the button once.
3. Open the new entry's **Configure → Check connection**. Wake the sensor again.
   The dialog checks the exact binding and reads the H10's current temperature.
   Warm the sensor slightly and repeat the check to confirm the H10 follows it.

There is one entry per circuit. In **Configure**, you can check, restore or
disconnect the assignment. Before replacing a sensor, disconnect it there with
the old sensor awake, delete the entry, then add the circuit with the new sensor.
Deleting the Home Assistant entry alone leaves the radio binding intact.

If you previously assigned another sensor to that circuit manually, remove the
old binding before adding the new one. The H10 can consume reports from
multiple sources on the same endpoint and may use the latest report.

Circuit numbers refer to the H10's thermostat endpoints. In a two-pipe system
they correspond to outputs 1–10. On four-pipe setups, follow the H10's configured
heating/cooling assignments. Check the room temperature and reporting cadence
before relying on the setup for heating.

[ubisys H10 technical reference](https://www.ubisys.de/downloads/ubisys-h10-technical-reference.pdf)
