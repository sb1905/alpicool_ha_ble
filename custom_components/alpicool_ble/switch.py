"""Switch platform for the Alpicool BLE integration."""

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import FridgeApi, has_right_zone
from .const import CONF_DUAL_ZONE_MODES, DOMAIN
from .entity import AlpicoolEntity, get_option


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Alpicool switch entities."""
    api: FridgeApi = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlpicoolPowerSwitch(entry, api),
            AlpicoolEcoSwitch(entry, api),
            AlpicoolLockSwitch(entry, api),
        ]
    )


class AlpicoolPowerSwitch(AlpicoolEntity, SwitchEntity):
    """Switch the fridge itself on and off with one press.

    The climate entity does the same through its HVAC modes, but those are
    called "Cool" and "Off" and sit behind a menu. This is the plain power
    button of the fridge.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:power"

    def __init__(self, entry: ConfigEntry, api: FridgeApi) -> None:
        """Initialize the switch."""
        super().__init__(entry, api)
        self._attr_unique_id = f"{self._address}_power"
        self._attr_name = "Power"

    @property
    def is_on(self) -> bool | None:
        """Return true if the fridge is switched on."""
        if not self.available:
            return None
        powered_on = self.api.status.get("powered_on")
        if powered_on is None:
            return None
        return bool(powered_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the fridge on."""
        await self.api.async_set_values({"powered_on": True})
        await self._async_refresh_after_write()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the fridge off."""
        await self.api.async_set_values({"powered_on": False})
        await self._async_refresh_after_write()


class AlpicoolEcoSwitch(AlpicoolEntity, SwitchEntity):
    """Switch between the two run modes with one press.

    On is run mode 1 (Eco) and off is run mode 0 (Max), the same mapping the
    climate presets use. A dual zone fridge configured for fridge/freezer
    operation calls its two modes Fridge and Freezer, so there the switch is
    named Freezer.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, entry: ConfigEntry, api: FridgeApi) -> None:
        """Initialize the switch."""
        super().__init__(entry, api)
        # The id says "mode" because the switch started out under that name.
        self._attr_unique_id = f"{self._address}_mode"
        self._is_fridge_freezer = has_right_zone(api.status) and get_option(
            entry, CONF_DUAL_ZONE_MODES, False
        )
        self._attr_name = "Freezer" if self._is_fridge_freezer else "Eco"

    @property
    def is_on(self) -> bool | None:
        """Return true in run mode 1: Eco, or Freezer."""
        if not self.available:
            return None
        run_mode = self.api.status.get("run_mode")
        if run_mode is None:
            return None
        return run_mode == 1

    @property
    def icon(self) -> str:
        """Return an icon that tells the two modes apart at a glance."""
        if self._is_fridge_freezer:
            return "mdi:snowflake" if self.is_on else "mdi:fridge-outline"
        return "mdi:leaf" if self.is_on else "mdi:speedometer"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Select run mode 1: Eco, or Freezer."""
        await self.api.async_set_values({"run_mode": 1})
        await self._async_refresh_after_write()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Select run mode 0: Max, or Fridge."""
        await self.api.async_set_values({"run_mode": 0})
        await self._async_refresh_after_write()


class AlpicoolLockSwitch(AlpicoolEntity, SwitchEntity):
    """Lock the buttons on the fridge's own control panel."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, api: FridgeApi) -> None:
        """Initialize the switch."""
        super().__init__(entry, api)
        self._attr_unique_id = f"{self._address}_lock"
        self._attr_name = "Panel Lock"

    @property
    def icon(self) -> str:
        """Return a closed or an open padlock."""
        return "mdi:lock" if self.is_on else "mdi:lock-open-variant"

    @property
    def is_on(self) -> bool | None:
        """Return true if the lock is on."""
        if not self.available:
            return None
        return self.api.status.get("locked", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lock on."""
        await self.api.async_set_values({"locked": True})
        await self._async_refresh_after_write()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lock off."""
        await self.api.async_set_values({"locked": False})
        await self._async_refresh_after_write()

