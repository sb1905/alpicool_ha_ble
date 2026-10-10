"""Binary sensor platform for the Alpicool BLE integration."""

from datetime import timedelta
import time
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .api import FridgeApi
from .const import DOMAIN
from .entity import AlpicoolEntity

# An idle voltage from before a restart is only trusted this long. After
# that the fridge may be on a different power source.
RESTORE_MAX_AGE = timedelta(hours=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alpicool binary sensor entities."""
    api: FridgeApi = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AlpicoolCompressorSensor(entry, api)])


class AlpicoolCompressorSensor(AlpicoolEntity, BinarySensorEntity, RestoreEntity):
    """Whether the compressor is running, estimated from the supply voltage.

    The fridge does not report its compressor, so this is not a measurement.
    The attributes show what the estimate rests on: the voltage taken as idle
    and how far the latest reading is below it.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:snowflake"

    def __init__(self, entry: ConfigEntry, api: FridgeApi) -> None:
        """Initialize the sensor."""
        super().__init__(entry, api)
        self._attr_unique_id = f"{self._address}_compressor"
        self._attr_name = "Compressor"

    async def async_added_to_hass(self) -> None:
        """Hand the idle voltage from before a restart back to the estimator.

        Otherwise a restart of Home Assistant in the middle of a run takes the
        lowered voltage for idle and misses that run.
        """
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        if dt_util.utcnow() - last_state.last_updated > RESTORE_MAX_AGE:
            return
        idle_voltage = last_state.attributes.get("idle_voltage")
        if isinstance(idle_voltage, (int, float)):
            self.api.compressor.restore(time.monotonic(), round(idle_voltage * 10))

    @property
    def is_on(self) -> bool | None:
        """Return true while the compressor is estimated to be running."""
        if not self.available or not self.api.status:
            return None
        return bool(self.api.status.get("powered_on")) and (
            self.api.compressor.is_running
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the figures behind the estimate."""
        return {
            "estimated_from": "supply voltage",
            "idle_voltage": self.api.compressor.idle_voltage,
            "voltage_drop": self.api.compressor.voltage_drop,
        }
