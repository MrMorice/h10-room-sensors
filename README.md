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

## Assign room sensors on the H10

1. On a first installation, add **H10 Room Sensors** under **Settings → Devices
   & services → Add integration**. An update from 0.1 automatically imports
   existing assignments.
2. Open the **ubisys H10** device page. Click the configuration cog in
   **Device info** to open the room-sensor dialog.
3. Pick a sensor for each thermostat circuit and save. You can choose the same
   sensor for several circuits. Select **No room sensor** to disconnect.
4. Home Assistant retries pending changes in the background. A short button
   press on a sleeping Shelly BLU H&T ZB can speed up the next attempt. Check the
   measured temperature at the H10 in the dialog.

Use **Check Zigbee bindings** in the dialog to read the selected sensor’s actual binding table. The check lists stored H10 destinations and whether the sensor also reports to the coordinator. Wake a battery-powered sensor while the table is being read.

When replacing a sensor, the integration removes the old binding before
applying the new one. The H10 may use its configured backup behavior until
the new sensor delivers a report.

If you previously assigned another sensor to that circuit manually, remove the
old binding before adding the new one. The H10 can consume reports from
multiple sources on the same endpoint and may use the latest report.

Circuit numbers refer to the H10's thermostat endpoints. In a two-pipe system
they correspond to outputs 1–10. On four-pipe setups, follow the H10's configured
heating/cooling assignments. Check the room temperature and reporting cadence
before relying on the setup for heating.

[ubisys H10 technical reference](https://www.ubisys.de/downloads/ubisys-h10-technical-reference.pdf)
