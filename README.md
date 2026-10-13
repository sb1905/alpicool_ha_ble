# Alpicool, BrassMonkey, Ocean Comfort, MAENTUM, ... 12V/24V BLE Fridge Integration for Home Assistant

This is a Home Assistant Custom Component to control Alpicool, BrassMonkey, Ocean Comfort, MAENTUM or other compatible portable fridges via Bluetooth Low Energy (BLE).

This integration creates multiple entities in Home Assistant, allowing you to monitor and control all known aspects of your fridge.

## About this fork

This is [sb1905](https://github.com/sb1905)'s fork of [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble). On top of the original it adds:

* A fix for single-zone fridges that report an empty second zone (Alpicool CX, advertised as `AK1-…`). Without it only the target temperature can be set, while power, mode and lock are ignored.
* A **Power** switch and a one-press **Eco** switch.
* A **compressor indicator**: the thermostat shows `Cooling` or `Idle`, and there is a `Compressor` sensor. The fridge does not report this, so it is estimated from the dip in the supply voltage while the compressor runs.
* Plainer wording: a running fridge shows as `On` instead of `Cool`, and the lock is called what it is, a panel lock.

Versions are numbered by date, for example `2026.10.0`, so they cannot be confused with the original's `3.x` numbers.

### Credits

Nearly all of the code is the work of others:

* [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble), the integration this fork is based on.
* [Bascht74](https://github.com/Bascht74), whose contributions to that project include MAENTUM support, the documentation and tools, and a large part of the tests.
* klightspeed's [BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor), whose protocol notes the integration builds on.

The additions in this fork were built with support from [Claude](https://claude.ai), Anthropic's AI model.

## Features & Supported Entities

* **Climate:** A central `climate` entity for each cooling zone to:
    * Turn the fridge on and off.
    * Set the target temperature (in 1°C increments).
    * Switch between `Max` and `Eco` preset modes.
    * Display the current temperature.
* **Binary sensor:** `Compressor`, on while the compressor is estimated to be running. See [Compressor indicator](#compressor-indicator).
* **Sensor:** Separate `sensor` entities for diagnostic data:
    * Battery charge percentage.
    * Battery voltage.
    * Last update: when the fridge last sent its status. If that is more than 150 seconds ago, the other entities go unavailable and the connection is rebuilt.
* **Switch:** `switch` entities for:
    * **Power:** switches the fridge on and off with one press.
    * **Eco:** on is `Eco`, off is `Max`. One press switches between them.
    * **Panel Lock:** locks the buttons on the fridge's own control panel.
* **Number:** `number` entities to configure advanced settings directly from the UI:
    * Compressor start delay (in minutes).
    * Temperature hysteresis (return difference).
* **Select:** `select` entities to configure advanced settings directly from the UI:
    * Battery saver (`Low`, `Medium`, `High`). On a dashboard, a tile card with the action `select.select_next` turns it into a single button that steps to the next level.

## Compressor indicator

These fridges do not report whether the compressor is running. What they do report is the supply voltage, and a running compressor pulls it down a little: on an Alpicool CX on its mains adapter from 14.3 V to 14.0 V, in steps of 0.1 V.

The idle level is not fixed: the same adapter has been seen idling at 14.1 V for hours. So the integration takes the highest voltage of the last 45 minutes as the idle voltage and treats a reading at least 0.2 V below it as "running". While the temperature is falling, 0.1 V below is enough, and the old idle voltage is kept for as long as the fridge keeps cooling down. A fridge that gets warmer during a "run" has its compressor off, so the voltage at that moment becomes the idle voltage. The result is shown as `Cooling` / `Idle` on the thermostat and as the `Compressor` sensor, whose attributes `idle_voltage` and `voltage_drop` show what the estimate rests on.

Things to know:

* It is an estimate and it lags. The voltage moves in steps and the fridge is read every 30 seconds, so expect a delay of a minute or so in both directions.
* The idle voltage is remembered across a restart of Home Assistant for up to an hour. Without a recent one, a start in the middle of a run shows `Idle` until that run has ended.
* It was tuned on a mains adapter. On a car battery the voltage also moves with the engine and the state of charge, so it is less reliable there.
* A fridge that is switched off, or already colder than its target, always counts as idle.

## Dual-Zone Support
This integration supports !!!untested!!! **both single and dual-zone fridges**. 

* For **dual-zone** models, it will create two `climate` entities (`... Left` and `... Right`), which will both become available.
* For **single-zone** models, only one `climate` entity is created.
* Single-zone models that still send the long dual-zone status are recognised: either by `-128` as the second zone's temperature (MAENTUM ICECUBE X) or by a second zone that is zero throughout (Alpicool CX, advertised as `AK1-…`).

***
## MAENTUM cooler boxes (Plug-in Festivals GmbH)

MAENTUM compressor cooler boxes speak the same protocol.

| Model | Status |
|---|---|
| ICECUBE X 50 | Tested on 2026-09-25: advertises service `0x1234` (used for discovery) under the name `A1-…`; status and target temperature confirmed, settings are read correctly. Single zone. |
| Other MAENTUM / Plug-in Festivals boxes | Reported by users to use the same protocol, not tested here. Check your box with the probe script in [docs/maentum](docs/maentum/README.md). |

Notes:

* The box needs a Bluetooth receiver in range that can **connect**: a local adapter or an ESPHome Bluetooth proxy with `active: true`. Receivers that only listen, such as Shelly devices, are not enough.
* Close the MAENTUM app first; the box accepts only one connection at a time.
* The box answers without the "Bind" step, so the "Pair on start-up (Bind)" option can be switched off.

A guide (probe script, research notes, HACS vs. ESPHome comparison) is in [docs/maentum](docs/maentum/README.md).

***
## Installation

Easiest install is via [HACS](https://hacs.xyz/):

### Method 1: HACS (Recommended)
1.  [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sb1905&repository=alpicool_ha_ble&category=integration)
2.  Click "Download" at the bottom right. In HACS this fork is listed as "Alpicool BLE (sb1905)".
3.  Restart Home Assistant.

### Method 2: Manual Installation
1.  Download the latest release from this repository.
2.  Copy the `alpicool_ble` directory into the `custom_components` directory of your Home Assistant instance.
3.  Restart Home Assistant.

***
## Configuration

Configuration is done via the Home Assistant UI.

1.  Navigate to **Settings > Devices & Services**.
2.  Home Assistant should automatically discover your fridge if it is powered on and nearby. If so, click **Configure** on the discovered device card.
3.  If it's not discovered automatically, click **Add Integration**, search for "Alpicool BLE", and follow the prompts to select your device.
4.  Select "dual_zone_modes" if your freezer has a Freezer or Fridge Mode. This will disable seperate controls, when the device is in fridge mode.
5.  Press the pairing button on the fridge, if "APP" is written on the display.

***
## Technical Details & Protocol Quirks

The development of this integration revealed several quirks in the Alpicool BLE protocol that required specific workarounds in the code.

* **Inconsistent Protocol:** The rules for calculating packet length and checksums are not consistent across all commands.
* **Special Command Handling:** `BIND`, `QUERY`, `SET_LEFT`, and `SET_RIGHT` commands are treated as special cases with a different packet structure than more complex commands like `SET`.
* **Concatenated BLE Responses:** The fridge responds to `SET` commands by sending two packets concatenated into a single BLE notification: first an echo of the sent command, followed by a full status update. The notification handler was specifically rewritten to parse this data stream correctly and ignore the echo.
* **Signed Byte Conversion:** Temperature values are transmitted as signed 8-bit integers. The code correctly converts between negative temperature values (e.g., -20°C) and their unsigned byte representation (e.g., 236) for both sending and receiving data.
