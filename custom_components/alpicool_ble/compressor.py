"""Estimate whether the compressor is running from the supply voltage.

The fridge does not report its compressor. What it does report is the voltage
it is fed with, and a running compressor pulls that voltage down a little. On
an Alpicool CX on its mains adapter the reading sinks from 14.3 V to 14.0 V in
steps of 0.1 V while the compressor runs, and climbs back when it stops.

The idle level itself is not fixed: the same adapter has been seen idling at
14.1 V for hours. So the estimator does not compare against a fixed voltage
but against the highest voltage of the recent past, and reports the compressor
as running while the reading is clearly below that. The temperature backs this
up: while it falls, the compressor runs.

This is an estimate, tuned on a mains adapter. On a car battery the voltage
also moves for other reasons (engine, alternator, discharge), so expect it to
be less reliable there.
"""

from collections import deque

# All voltages here are in tenths of a volt: the resolution the fridge reports,
# and whole numbers avoid rounding trouble when comparing.

# Drop below the idle voltage at which the compressor counts as running. One
# tenth is within the noise of the reading, so it takes two, unless the
# temperature is falling at the same time.
ON_DROP = 2
# A drop this large is not the compressor: the power source changed, for
# example from mains adapter to battery, or an engine was switched off.
SOURCE_CHANGE_DROP = 8
# The highest voltage within this time is taken as the idle voltage. Longer
# than a normal run (12 to 14 minutes on a CX), so the voltage from before the
# run is still remembered, and short enough that an idle level that settles
# lower, or a draining battery, is followed within the hour.
BASELINE_SECONDS = 45 * 60
# When the compressor is known to be off (fridge switched off, or colder than
# its target), the voltage only needs time to recover from the last run. What
# it reads after this long is idle, so older, higher readings are dropped.
KNOWN_IDLE_SETTLE_SECONDS = 120
# A change of the inside temperature counts as its trend for this long. A
# running compressor lowers it by a degree every few minutes.
TREND_SECONDS = 15 * 60
# A zone that gets warmer during a run means the compressor is off and the
# supply idles lower than before. Not right at the start of a run, though:
# the fridge starts the compressor because it got warmer, and that reading
# can arrive a poll late.
RUN_GRACE_SECONDS = 120


class CompressorEstimator:
    """Track the idle voltage and tell when the compressor pulls it down."""

    def __init__(self) -> None:
        """Start without any knowledge of the supply."""
        # Readings that may serve as the idle voltage, as (time, voltage).
        self._readings: deque[tuple[float, int]] = deque()
        self._last_voltage: int | None = None
        self._known_idle_since: float | None = None
        self._temperatures: tuple[int, ...] = ()
        # Direction of the last temperature change (-1 or 1) and its time.
        self._trend = 0
        self._trend_time = 0.0
        self._running = False
        self._run_start = 0.0

    @property
    def is_running(self) -> bool:
        """Return True while the compressor is estimated to be running."""
        return self._running

    @property
    def _idle(self) -> int | None:
        """Return the idle voltage in tenths of a volt."""
        if not self._readings:
            return None
        return max(voltage for _, voltage in self._readings)

    @property
    def idle_voltage(self) -> float | None:
        """Return the voltage taken as "compressor idle", in volts."""
        idle = self._idle
        return None if idle is None else idle / 10

    @property
    def voltage_drop(self) -> float | None:
        """Return how far the last reading was below the idle voltage, in volts."""
        idle = self._idle
        if idle is None or self._last_voltage is None:
            return None
        return max(idle - self._last_voltage, 0) / 10

    def reset(self) -> None:
        """Forget everything, for example after the fridge was out of reach."""
        self._readings.clear()
        self._last_voltage = None
        self._known_idle_since = None
        self._temperatures = ()
        self._trend = 0
        self._running = False

    def _falling(self, now: float) -> bool:
        """Return True while the inside temperature is going down."""
        return self._trend < 0 and now - self._trend_time <= TREND_SECONDS

    def _follow_temperatures(self, now: float, temperatures: tuple[int, ...]) -> bool:
        """Note whether any zone got colder or warmer since the last reading.

        Returns True if it got warmer.
        """
        warmer = False
        if len(temperatures) == len(self._temperatures):
            changes = [new - old for new, old in zip(temperatures, self._temperatures)]
            if any(change < 0 for change in changes):
                self._trend, self._trend_time = -1, now
            elif any(change > 0 for change in changes):
                self._trend, self._trend_time = 1, now
                warmer = True
        self._temperatures = temperatures
        return warmer

    def _set_running(self, now: float, running: bool) -> None:
        """Take in a new estimate, noting when a run starts."""
        if running and not self._running:
            self._run_start = now
        self._running = running

    def restore(self, now: float, idle_voltage: int) -> None:
        """Start from an idle voltage learned earlier, before a restart.

        The first reading after a start is taken as idle, which is wrong when
        the compressor happens to be running at that moment. A higher idle
        voltage known from just before the restart corrects that at once.
        """
        idle = self._idle
        if idle is not None and idle_voltage <= idle:
            return
        last = self._last_voltage
        if last is not None and idle_voltage - last >= SOURCE_CHANGE_DROP:
            # Too far above what the fridge is fed with now to be the same supply.
            return
        self._readings.append((now, idle_voltage))
        if last is not None:
            self._set_running(now, self._judge(now, last))

    def update(
        self,
        now: float,
        voltage: int,
        *,
        powered_on: bool,
        satisfied: bool,
        temperatures: tuple[int, ...] = (),
    ) -> bool:
        """Take in one status reading and return the new estimate.

        now: a monotonic time in seconds.
        voltage: the supply voltage in tenths of a volt.
        powered_on: whether the fridge is switched on.
        satisfied: whether every zone is already colder than its target, in
            which case the fridge has no reason to run the compressor.
        temperatures: the current temperature of each zone.
        """
        previous = self._last_voltage
        self._last_voltage = voltage
        warmer = self._follow_temperatures(now, temperatures)
        if powered_on and not satisfied:
            self._known_idle_since = None
        elif self._known_idle_since is None:
            self._known_idle_since = now

        idle = self._idle
        if idle is None or idle - voltage >= SOURCE_CHANGE_DROP:
            # Nothing known yet, or a new power source: start over from here.
            self._readings.clear()
            self._readings.append((now, voltage))
            self._running = False
            return False

        if voltage - idle >= 2 and previous is not None:
            # A lone jump of two steps or more only counts once the next
            # reading confirms it. A single outlier would otherwise make the
            # normal voltage look like a drop for the whole window. One step
            # up is how the voltage recovers after a run, so that counts at once.
            self._readings.append((now, min(previous, voltage)))
        else:
            self._readings.append((now, voltage))
        self._forget_old_readings(now)

        if warmer and self._running and now - self._run_start >= RUN_GRACE_SECONDS:
            # Not what a running compressor does: it is off, and the supply
            # idles lower than before. Start over from this reading.
            self._readings.clear()
            self._readings.append((now, voltage))

        self._set_running(now, self._judge(now, voltage))
        return self._running

    def _forget_old_readings(self, now: float) -> None:
        """Drop readings too old to tell the idle voltage any more."""
        if (
            self._known_idle_since is not None
            and now - self._known_idle_since >= KNOWN_IDLE_SETTLE_SECONDS
        ):
            cutoff = now - KNOWN_IDLE_SETTLE_SECONDS
        elif self._falling(now):
            # Still cooling down, as on a long pull-down from room temperature:
            # the voltage from before the run is still the idle voltage.
            return
        else:
            cutoff = now - BASELINE_SECONDS
        while len(self._readings) > 1 and self._readings[0][0] < cutoff:
            self._readings.popleft()

    def _judge(self, now: float, voltage: int) -> bool:
        """Decide whether a reading means the compressor is running."""
        if self._known_idle_since is not None:
            # The compressor cannot be running. The voltage is recovering from
            # the last run, or the supply itself went down a little.
            return False
        drop = self._idle - voltage
        return drop >= ON_DROP or (drop >= 1 and self._falling(now))
