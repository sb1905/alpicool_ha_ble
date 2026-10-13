"""The Alpicool BLE integration."""

import asyncio
from datetime import datetime, timedelta

from bleak.exc import BleakError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .api import FridgeApi
from .const import CONF_BIND_ON_START, DEFAULT_BIND_ON_START, DOMAIN, POLL_INTERVAL
from .entity import get_option

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Entities that builds of this fork from before 2026.10.0 created and that no
# longer exist, as (platform, unique id suffix): three battery saver switches
# that duplicated the Battery Saver select, and five sensors for undecoded
# status values that turned out to tell nothing.
RETIRED_ENTITIES: list[tuple[Platform, str]] = [
    (Platform.SWITCH, "battery_saver_low"),
    (Platform.SWITCH, "battery_saver_medium"),
    (Platform.SWITCH, "battery_saver_high"),
    (Platform.SENSOR, "raw_status_19"),
    (Platform.SENSOR, "raw_status_20"),
    (Platform.SENSOR, "raw_status_27"),
    (Platform.SENSOR, "raw_status_28"),
    (Platform.SENSOR, "raw_status_29"),
]


@callback
def _async_remove_retired_entities(hass: HomeAssistant, address: str) -> None:
    """Delete registry entries of entities this integration no longer provides.

    Without this they would linger as "no longer provided by the integration".
    """
    registry = er.async_get(hass)
    for platform, suffix in RETIRED_ENTITIES:
        entity_id = registry.async_get_entity_id(
            platform, DOMAIN, f"{address}_{suffix}"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alpicool BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    address = entry.data["address"]

    api = FridgeApi(hass, address)
    hass.data[DOMAIN][entry.entry_id] = api

    # Reconnect as soon as the fridge shows up again instead of waiting for the
    # next poll tick.
    entry.async_on_unload(api.async_register_advertisement_callback())
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    if (reason := api.async_reachability()) is not None:
        raise ConfigEntryNotReady(reason)

    try:
        if not await api.connect(
            bind=get_option(entry, CONF_BIND_ON_START, DEFAULT_BIND_ON_START)
        ):
            raise ConfigEntryNotReady(
                f"Could not connect to Alpicool device at {address}"
            )
        if not await api.update_status():
            raise ConfigEntryNotReady(
                f"Could not get initial status from Alpicool device at {address}"
            )
    except BleakError as e:
        await api.disconnect()
        raise ConfigEntryNotReady(
            f"Failed to initialize Alpicool device at {address}: {e}"
        ) from e

    api.set_initial_timestamp()

    _async_remove_retired_entities(hass, address)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _async_send_update() -> None:
        async_dispatcher_send(hass, f"{DOMAIN}_{address}_update")

    @callback
    def _async_start_polling() -> asyncio.Task:
        return entry.async_create_background_task(
            hass, api.start_polling(_async_send_update), name="alpicool_ble_poll"
        )

    poll_task = _async_start_polling()

    async def _async_reconnect() -> None:
        """Drop the connection and start polling afresh."""
        nonlocal poll_task
        poll_task.cancel()
        await api.disconnect()
        poll_task = _async_start_polling()

    @callback
    def _async_watchdog(now: datetime) -> None:
        """Catch a connection that went quiet without being dropped."""
        if api.async_check_stale():
            _async_send_update()
            entry.async_create_background_task(
                hass, _async_reconnect(), name="alpicool_ble_reconnect"
            )

    entry.async_on_unload(
        async_track_time_interval(
            hass, _async_watchdog, timedelta(seconds=POLL_INTERVAL)
        )
    )

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        api: FridgeApi = hass.data[DOMAIN].pop(entry.entry_id)
        await api.disconnect()

    return unload_ok
