"""Tests for the Alpicool switch entities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alpicool_ble.const import CONF_DUAL_ZONE_MODES, DOMAIN
from custom_components.alpicool_ble.switch import (
    AlpicoolConnectionSwitch,
    AlpicoolLockSwitch,
    AlpicoolEcoSwitch,
    AlpicoolPowerSwitch,
    async_setup_entry,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, data={"address": ADDRESS, "name": "Fridge"}, options=options
    )


def _api(**status) -> MagicMock:
    api = MagicMock()
    api.status = status
    api.is_available = True
    api.async_set_values = AsyncMock()
    api.update_status = AsyncMock(return_value=True)
    return api


async def test_setup_adds_power_mode_and_lock() -> None:
    """One switch each. The battery saver level is set with the select."""
    added: list = []
    hass = MagicMock()
    entry = _entry()
    hass.data = {DOMAIN: {entry.entry_id: _api(bat_saver=2)}}

    await async_setup_entry(hass, entry, added.extend)

    assert [e.unique_id for e in added] == [
        f"{ADDRESS}_power",
        f"{ADDRESS}_mode",
        f"{ADDRESS}_lock",
        f"{ADDRESS}_connection",
    ]


# --- Panel lock ------------------------------------------------------------


def test_lock_is_named_after_what_it_locks() -> None:
    """It locks the control panel, not the lid; the unique id stays as it was."""
    lock = AlpicoolLockSwitch(_entry(), _api(locked=False))

    assert lock.name == "Panel Lock"
    assert lock.unique_id == f"{ADDRESS}_lock"


def test_lock_icon_follows_the_lock() -> None:
    """A closed padlock when locked, an open one otherwise."""
    entry = _entry()
    assert AlpicoolLockSwitch(entry, _api(locked=True)).icon == "mdi:lock"
    assert (
        AlpicoolLockSwitch(entry, _api(locked=False)).icon == "mdi:lock-open-variant"
    )


# --- Power -----------------------------------------------------------------


def test_power_follows_the_fridge() -> None:
    """The switch shows whether the fridge itself is on."""
    entry = _entry()
    assert AlpicoolPowerSwitch(entry, _api(powered_on=True)).is_on is True
    assert AlpicoolPowerSwitch(entry, _api(powered_on=False)).is_on is False


def test_power_is_unknown_without_a_reading() -> None:
    """No status yet, or a fridge that is away, is not the same as off."""
    assert AlpicoolPowerSwitch(_entry(), _api()).is_on is None

    switch = AlpicoolPowerSwitch(_entry(), _api(powered_on=True))
    switch.api.is_available = False
    assert switch.is_on is None


@pytest.mark.parametrize(("method", "value"), [("turn_on", True), ("turn_off", False)])
async def test_power_is_sent_to_the_fridge(method: str, value: bool) -> None:
    """One press sends the new power state and reads the result back."""
    switch = AlpicoolPowerSwitch(_entry(), _api(powered_on=not value))
    switch.hass = MagicMock()

    await getattr(switch, f"async_{method}")()

    switch.api.async_set_values.assert_awaited_once_with({"powered_on": value})
    switch.api.update_status.assert_awaited_once()


# --- Eco ---------------------------------------------------------------------


def test_eco_is_on_in_eco_mode() -> None:
    """Run mode 1 is Eco and shows as on; run mode 0 is Max and shows as off."""
    entry = _entry()
    assert AlpicoolEcoSwitch(entry, _api(run_mode=1)).is_on is True
    assert AlpicoolEcoSwitch(entry, _api(run_mode=0)).is_on is False
    assert AlpicoolEcoSwitch(entry, _api()).is_on is None


@pytest.mark.parametrize(("method", "run_mode"), [("turn_on", 1), ("turn_off", 0)])
async def test_eco_is_sent_to_the_fridge(method: str, run_mode: int) -> None:
    """One press sends the other run mode and reads the result back."""
    switch = AlpicoolEcoSwitch(_entry(), _api(run_mode=1 - run_mode))
    switch.hass = MagicMock()

    await getattr(switch, f"async_{method}")()

    switch.api.async_set_values.assert_awaited_once_with({"run_mode": run_mode})
    switch.api.update_status.assert_awaited_once()


def test_switch_is_named_eco_by_default() -> None:
    """Single zone fridges, and dual zone ones without the option, have Max/Eco."""
    assert AlpicoolEcoSwitch(_entry(), _api(run_mode=0)).name == "Eco"

    # The option alone does not make a single zone fridge a fridge/freezer.
    entry = _entry(**{CONF_DUAL_ZONE_MODES: True})
    assert AlpicoolEcoSwitch(entry, _api(run_mode=0)).name == "Eco"

    dual = _api(run_mode=0, right_current=-8)
    assert AlpicoolEcoSwitch(_entry(), dual).name == "Eco"


def test_switch_is_named_freezer_when_configured() -> None:
    """A dual zone fridge with the option has the modes Fridge and Freezer."""
    entry = _entry(**{CONF_DUAL_ZONE_MODES: True})
    switch = AlpicoolEcoSwitch(entry, _api(run_mode=1, right_current=-8))

    assert switch.name == "Freezer"
    assert switch.is_on is True


def test_the_unique_id_survives_the_rename() -> None:
    """The switch was called Mode at first; existing entities must carry over."""
    assert AlpicoolEcoSwitch(_entry(), _api()).unique_id == f"{ADDRESS}_mode"


def test_eco_icon_follows_the_mode() -> None:
    """A leaf for Eco, a speedometer for Max."""
    entry = _entry()
    assert AlpicoolEcoSwitch(entry, _api(run_mode=1)).icon == "mdi:leaf"
    assert AlpicoolEcoSwitch(entry, _api(run_mode=0)).icon == "mdi:speedometer"


# --- Bluetooth connection --------------------------------------------------


def _connection_switch(api: MagicMock) -> AlpicoolConnectionSwitch:
    switch = AlpicoolConnectionSwitch(_entry(), api)
    switch.hass = MagicMock()
    return switch


def test_connection_switch_stays_available_while_released() -> None:
    """Otherwise it could not be switched back on."""
    api = _api()
    api.is_available = False
    api.is_released = True
    switch = _connection_switch(api)

    assert switch.available is True
    assert switch.is_on is False
    assert switch.unique_id == f"{ADDRESS}_connection"


async def test_connection_switch_releases_and_resumes() -> None:
    """Off releases the connection, on takes it back; all entities refresh."""
    api = _api()
    api.is_released = False
    api.async_release = AsyncMock()
    api.async_resume = MagicMock()
    switch = _connection_switch(api)

    with patch(
        "custom_components.alpicool_ble.switch.async_dispatcher_send"
    ) as send:
        await switch.async_turn_off()
        api.async_release.assert_awaited_once()
        await switch.async_turn_on()
        api.async_resume.assert_called_once()

    assert send.call_count == 2
    assert send.call_args.args[1] == f"alpicool_ble_{ADDRESS}_update"
