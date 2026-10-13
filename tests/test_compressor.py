"""Tests for the compressor estimate from the supply voltage."""

import pytest

from custom_components.alpicool_ble.compressor import (
    BASELINE_SECONDS,
    KNOWN_IDLE_SETTLE_SECONDS,
    CompressorEstimator,
)

# One status reading every 30 seconds, as the integration polls.
STEP = 30


def feed(
    estimator: CompressorEstimator,
    voltages: list[int],
    *,
    start: float = 0,
    powered_on: bool = True,
    satisfied: bool = False,
    temperatures: list[int] | None = None,
) -> list[bool]:
    """Feed readings 30 s apart and return the estimate after each one."""
    return [
        estimator.update(
            start + index * STEP,
            voltage,
            powered_on=powered_on,
            satisfied=satisfied,
            temperatures=() if temperatures is None else (temperatures[index],),
        )
        for index, voltage in enumerate(voltages)
    ]


def test_first_reading_is_taken_as_idle() -> None:
    """Nothing is known yet, so the first voltage becomes the reference."""
    estimator = CompressorEstimator()
    assert estimator.idle_voltage is None

    assert feed(estimator, [143]) == [False]
    assert estimator.idle_voltage == 14.3
    assert estimator.voltage_drop == 0.0


def test_cx_on_mains_adapter() -> None:
    """The run seen on an Alpicool CX: 14.3 V sinks to 14.0 V in steps, then recovers."""
    estimator = CompressorEstimator()

    readings = [143, 143, 142, 141, 140, 140, 140, 141, 142, 143, 143]
    expected = [False, False, False, True, True, True, True, True, False, False, False]

    assert feed(estimator, readings) == expected
    assert estimator.idle_voltage == 14.3


def test_one_tenth_of_noise_is_not_the_compressor() -> None:
    """A single step down happens without the compressor too."""
    estimator = CompressorEstimator()

    assert feed(estimator, [143, 142, 143, 142, 142, 143]) == [False] * 6


def test_a_long_run_stays_running() -> None:
    """Pulling down from room temperature takes hours; the reference must hold."""
    estimator = CompressorEstimator()
    feed(estimator, [143, 143, 141], temperatures=[25, 25, 25])

    # One degree colder every five minutes, for three hours.
    temperatures = [24 - index // 10 for index in range(360)]
    three_hours = feed(
        estimator, [140] * 360, start=3 * STEP, temperatures=temperatures
    )

    assert all(three_hours)
    assert estimator.idle_voltage == 14.3
    assert estimator.voltage_drop == 0.3


def test_switching_the_fridge_off_ends_the_run() -> None:
    """A fridge that is off has no running compressor, whatever the voltage."""
    estimator = CompressorEstimator()
    assert feed(estimator, [143, 143, 140])[-1] is True

    assert feed(estimator, [140], start=90, powered_on=False) == [False]
    assert estimator.is_running is False


def test_a_fridge_colder_than_its_target_is_idle() -> None:
    """Raising the target above the inside temperature stops the compressor."""
    estimator = CompressorEstimator()
    assert feed(estimator, [143, 143, 140])[-1] is True

    assert feed(estimator, [140, 141], start=90, satisfied=True) == [False, False]

    # The voltage keeps recovering afterwards and the reference follows it.
    assert feed(estimator, [142, 143, 143], start=150) == [False, False, False]
    assert estimator.idle_voltage == 14.3


def test_a_change_of_power_source_is_not_a_run() -> None:
    """From the mains adapter to a battery the voltage falls far more than a compressor pulls."""
    estimator = CompressorEstimator()
    feed(estimator, [143, 143])

    assert feed(estimator, [127, 127, 127], start=60) == [False, False, False]
    assert estimator.idle_voltage == 12.7

    # On the new source a compressor run is seen again.
    assert feed(estimator, [125, 124, 126, 127], start=150) == [
        True,
        True,
        False,
        False,
    ]


def test_a_single_high_reading_does_not_raise_the_reference() -> None:
    """One outlier must not make the normal voltage look like a drop."""
    estimator = CompressorEstimator()

    assert feed(estimator, [143, 146, 143, 143, 143]) == [False] * 5
    assert estimator.idle_voltage == 14.3


def test_the_reference_follows_a_supply_that_really_rose() -> None:
    """After a start during a run the first reading was too low."""
    estimator = CompressorEstimator()
    # Home Assistant started while the compressor was running at 14.0 V.
    assert feed(estimator, [140, 140, 141, 142, 143, 143]) == [False] * 6
    assert estimator.idle_voltage == 14.3

    # From the next run on the estimate is right.
    assert feed(estimator, [142, 141, 140], start=180) == [False, True, True]


def test_recovery_is_followed_one_step_at_a_time() -> None:
    """A run that starts before the voltage has fully recovered is still seen.

    This went wrong on a real fridge: the target was lowered again while the
    voltage was still climbing back, the reference stayed one step too low,
    and the next run from 14.3 V to 14.1 V did not register.
    """
    estimator = CompressorEstimator()
    # Colder than the target, so known to be idle; still recovering.
    feed(estimator, [141, 142], satisfied=True)

    # The target is lowered. One reading at 14.3 V, then the compressor starts.
    assert feed(estimator, [142, 143, 142, 141, 141], start=60) == [
        False,
        False,
        False,
        True,
        True,
    ]
    assert estimator.idle_voltage == 14.3


def test_known_idle_does_not_take_a_recovering_voltage_as_the_reference() -> None:
    """Right after a run the voltage is still low although the compressor is off."""
    estimator = CompressorEstimator()
    assert feed(estimator, [143, 143, 140])[-1] is True

    # The target is raised: the compressor stops and the voltage climbs back.
    assert feed(estimator, [140, 141, 142, 143], start=90, satisfied=True) == [
        False
    ] * 4
    assert estimator.idle_voltage == 14.3


def test_known_idle_accepts_a_lower_supply_after_a_short_while() -> None:
    """If the voltage does not come back, the supply itself went down."""
    estimator = CompressorEstimator()
    feed(estimator, [143, 143])

    readings = [140] * (KNOWN_IDLE_SETTLE_SECONDS // STEP + 2)
    assert not any(feed(estimator, readings, start=60, satisfied=True))
    assert estimator.idle_voltage == 14.0


def test_restore_corrects_a_start_in_mid_run() -> None:
    """With the idle voltage from before the restart, the current run is seen."""
    estimator = CompressorEstimator()
    # Home Assistant restarts while the compressor runs at 14.1 V.
    assert feed(estimator, [141]) == [False]
    assert estimator.idle_voltage == 14.1

    estimator.restore(10, 143)

    assert estimator.is_running is True
    assert estimator.idle_voltage == 14.3
    assert feed(estimator, [141, 140, 142, 143], start=30) == [
        True,
        True,
        False,
        False,
    ]


def test_restore_keeps_an_idle_fridge_idle() -> None:
    """A remembered voltage at or below the present one changes nothing."""
    estimator = CompressorEstimator()
    feed(estimator, [143])

    estimator.restore(10, 143)
    estimator.restore(10, 141)

    assert estimator.is_running is False
    assert estimator.idle_voltage == 14.3


def test_restore_does_not_start_a_run_on_a_fridge_known_to_be_idle() -> None:
    """Colder than its target: a lower voltage is not the compressor."""
    estimator = CompressorEstimator()
    feed(estimator, [141], satisfied=True)

    estimator.restore(10, 143)

    assert estimator.is_running is False


def test_restore_ignores_a_voltage_from_another_power_source() -> None:
    """14.3 V from the mains adapter says nothing about a 12.7 V battery."""
    estimator = CompressorEstimator()
    feed(estimator, [127])

    estimator.restore(10, 143)

    assert estimator.is_running is False
    assert estimator.idle_voltage == 12.7


def test_the_reference_follows_a_slowly_draining_battery() -> None:
    """While idle, a voltage that settles one tenth lower becomes the reference."""
    estimator = CompressorEstimator()
    feed(estimator, [128, 128])

    readings = [127] * (BASELINE_SECONDS // STEP + 2)
    assert not any(feed(estimator, readings, start=60))
    assert estimator.idle_voltage == 12.7

    # Without that, this second tenth would have looked like a compressor run.
    assert feed(estimator, [126], start=60 + len(readings) * STEP) == [False]


def cycle(idle: int, running: int, cold: int) -> tuple[list[int], list[int]]:
    """Return the voltages and temperatures of one 50 minute cycle.

    13 minutes running while it cools down by two degrees, then 37 minutes
    idle while it warms up again.
    """
    voltages = [running] * 26 + [idle] * 74
    temperatures = [cold + 2] * 9 + [cold + 1] * 9 + [cold] * 33 + [cold + 1] * 25
    temperatures += [cold + 2] * (100 - len(temperatures))
    return voltages, temperatures


def test_an_idle_level_that_settles_lower_is_followed() -> None:
    """Seen on 12 Oct: the fridge idled at 14.1 V instead of 14.3 V for hours.

    With a fixed reference the compressor showed as running all that time,
    while the temperature kept cycling normally.
    """
    estimator = CompressorEstimator()
    voltages, temperatures = cycle(143, 141, 4)
    feed(estimator, voltages, temperatures=temperatures)
    assert estimator.idle_voltage == 14.3

    # From now on it idles at 14.1 V and runs at 14.0 V.
    voltages, temperatures = cycle(141, 140, 4)
    cycles = [
        feed(estimator, voltages, start=n * 100 * STEP, temperatures=temperatures)
        for n in range(1, 5)
    ]

    # Within the hour the idle phases read idle again...
    assert not any(cycles[2][26:])
    assert not any(cycles[3][26:])
    # ...and a run, one tenth down while the temperature falls, still shows.
    assert any(cycles[3][:26])
    assert estimator.idle_voltage == 14.1


def test_getting_warmer_ends_a_run() -> None:
    """Seen on 12 Oct: after a run the voltage stayed at 14.1 V, two tenths low.

    Once the fridge warms up again the compressor is clearly off, so 14.1 V
    is idle from then on.
    """
    estimator = CompressorEstimator()
    feed(estimator, [143, 143], temperatures=[6, 6])

    # It runs for ten minutes and cools down, then stops at 14.1 V.
    temperatures = [6] * 10 + [5] * 10 + [4] * 20
    run = feed(estimator, [140] + [141] * 39, start=60, temperatures=temperatures)
    assert all(run)

    after = feed(estimator, [141, 141], start=1260, temperatures=[5, 5])
    assert after == [False, False]
    assert estimator.idle_voltage == 14.1


def test_getting_warmer_right_at_the_start_does_not_end_the_run() -> None:
    """The reading that made the fridge start its compressor can come a poll late."""
    estimator = CompressorEstimator()
    feed(estimator, [143, 143], temperatures=[5, 5])

    run = feed(estimator, [140, 140, 141], start=60, temperatures=[5, 6, 6])
    assert run == [True] * 3
    assert estimator.idle_voltage == 14.3


def test_one_tenth_down_counts_while_the_temperature_falls() -> None:
    """The temperature tells a small dip from noise."""
    estimator = CompressorEstimator()
    feed(estimator, [141, 141], temperatures=[6, 6])

    assert feed(estimator, [140], start=60, temperatures=[6]) == [False]
    assert feed(estimator, [140], start=90, temperatures=[5]) == [True]
    assert feed(estimator, [141], start=120, temperatures=[5]) == [False]


def test_reset_forgets_the_supply() -> None:
    """After the fridge was out of reach the old reference is not trusted."""
    estimator = CompressorEstimator()
    feed(estimator, [143, 143, 140])

    estimator.reset()

    assert estimator.is_running is False
    assert estimator.idle_voltage is None
    assert estimator.voltage_drop is None


@pytest.mark.parametrize("voltage", [0, 255])
def test_odd_readings_do_not_raise(voltage: int) -> None:
    """A fridge without a voltage reading must not break anything."""
    estimator = CompressorEstimator()

    assert feed(estimator, [voltage, voltage, voltage]) == [False] * 3
