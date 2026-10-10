"""Estimate whether the compressor is running from the supply voltage.

The fridge does not report its compressor. What it does report is the voltage
it is fed with, and a running compressor pulls that voltage down a little. On
an Alpicool CX on its mains adapter the reading sinks from 14.3 V to 14.0 V in
steps of 0.1 V while the compressor runs, and climbs back when it stops.

The estimator remembers the voltage seen while idle and reports the compressor
as running while the reading is clearly below it. This is an estimate, tuned
on a mains adapter. On a car battery the voltage also moves for other reasons
(engine, alternator, discharge), so expect it to be less reliable there.
"""

# All voltages here are in tenths of a volt: the resolution the fridge reports,
# and whole numbers avoid rounding trouble when comparing.

# Drop below the idle voltage at which the compressor counts as running. One
# tenth is within the noise of the reading, so it takes two.
ON_DROP = 2
# A drop this large is not the compressor: the power source changed, for
# example from mains adapter to battery, or an engine was switched off.
SOURCE_CHANGE_DROP = 8
# While idle, a reading that stays slightly below the idle voltage for this
# long becomes the new idle voltage. This follows a slowly draining battery.
IDLE_SETTLE_SECONDS = 600
# The same, for when the compressor is known to be off (fridge switched off,
# or colder than its target). The voltage only needs time to recover from the
# last run, so a reading that is still lower after this is the new normal.
KNOWN_IDLE_SETTLE_SECONDS = 120


class CompressorEstimator:
    """Track the idle voltage and tell when the compressor pulls it down."""

    def __init__(self) -> None:
        """Start without any knowledge of the supply."""
        self._idle_voltage: int | None = None
        self._last_voltage: int | None = None
        self._below_idle_since: float | None = None
        self._known_idle = False
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return True while the compressor is estimated to be running."""
        return self._running

    @property
    def idle_voltage(self) -> float | None:
        """Return the voltage taken as "compressor idle", in volts."""
        if self._idle_voltage is None:
            return None
        return self._idle_voltage / 10

    @property
    def voltage_drop(self) -> float | None:
        """Return how far the last reading was below the idle voltage, in volts."""
        if self._idle_voltage is None or self._last_voltage is None:
            return None
        return max(self._idle_voltage - self._last_voltage, 0) / 10

    def reset(self) -> None:
        """Forget everything, for example after the fridge was out of reach."""
        self._idle_voltage = None
        self._last_voltage = None
        self._below_idle_since = None
        self._known_idle = False
        self._running = False

    def _start_over(self, voltage: int) -> None:
        """Take a reading as the idle voltage, dropping what was known before."""
        self._idle_voltage = voltage
        self._below_idle_since = None
        self._running = False

    def restore(self, now: float, idle_voltage: int) -> None:
        """Start from an idle voltage learned earlier, before a restart.

        The first reading after a start is taken as idle, which is wrong when
        the compressor happens to be running at that moment. A higher idle
        voltage known from just before the restart corrects that at once.
        """
        if self._idle_voltage is not None and idle_voltage <= self._idle_voltage:
            return
        last = self._last_voltage
        if last is None:
            self._idle_voltage = idle_voltage
            return
        if idle_voltage - last >= SOURCE_CHANGE_DROP:
            # Too far above what the fridge is fed with now to be the same supply.
            return
        self._idle_voltage = idle_voltage
        self._below_idle_since = None
        if last < idle_voltage:
            self._judge_reading_below_idle(now, last)

    def update(
        self, now: float, voltage: int, *, powered_on: bool, satisfied: bool
    ) -> bool:
        """Take in one status reading and return the new estimate.

        now: a monotonic time in seconds.
        voltage: the supply voltage in tenths of a volt.
        powered_on: whether the fridge is switched on.
        satisfied: whether every zone is already colder than its target, in
            which case the fridge has no reason to run the compressor.
        """
        previous = self._last_voltage
        self._last_voltage = voltage
        self._known_idle = not powered_on or satisfied

        if self._idle_voltage is None:
            self._start_over(voltage)
            return False

        if voltage >= self._idle_voltage:
            rise = voltage - self._idle_voltage
            if previous is not None and previous > self._idle_voltage:
                # The second higher reading in a row confirms a larger jump.
                self._idle_voltage = min(previous, voltage)
            elif rise == 1:
                # One step up is how the voltage recovers after a run, so the
                # reference follows at once.
                self._idle_voltage = voltage
            # A lone jump of two steps or more waits for a second reading. A
            # single outlier would otherwise make the normal voltage look like
            # a drop from then on.
            self._below_idle_since = None
            self._running = False
            return False

        return self._judge_reading_below_idle(now, voltage)

    def _judge_reading_below_idle(self, now: float, voltage: int) -> bool:
        """Decide what a reading below the idle voltage means."""
        drop = self._idle_voltage - voltage

        if drop >= SOURCE_CHANGE_DROP:
            self._start_over(voltage)
            return False

        if self._known_idle:
            # The compressor cannot be running. The voltage is recovering from
            # the last run, or the supply itself went down a little.
            self._running = False
            settle = KNOWN_IDLE_SETTLE_SECONDS
        else:
            # At two steps or more it runs; at one step it does not (any more).
            self._running = drop >= ON_DROP
            settle = IDLE_SETTLE_SECONDS

        if self._running:
            self._below_idle_since = None
        elif self._below_idle_since is None:
            self._below_idle_since = now
        elif now - self._below_idle_since >= settle:
            self._idle_voltage = voltage
            self._below_idle_since = None

        return self._running
