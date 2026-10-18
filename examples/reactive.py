"""Closed-loop example: decide from telemetry at every update.

Each burn gets a planned stop: a command scheduled in the future for the moment the wheel momentum
would reach a margin below its limit, or the moment the delta-v goal would be reached.
The planned stop is canceled and replaced whenever the strategy learns something new,
and canceled outright when the temperature forces an earlier stop.
Thruster accelerations are estimated from telemetry, so a thruster that underperforms the nominal model
simply burns longer.
"""

from spacecraft_ops import (
    Commander,
    CommandId,
    CompleteMission,
    MissionBrief,
    PropulsionMode,
    SetHeater,
    SetPropulsionMode,
    Strategy,
    Telemetry,
)

OFF = PropulsionMode.OFF
HOT_MARGIN_C = 8.0
"""Stop firing this far below the maximum temperature."""
COOLING_BAND_C = 10.0
"""Cool down by this much before firing again."""
HEATER_ON_MARGIN_C = 5.0
"""Switch the heater on this far above the minimum temperature, and off again twice as far."""
MOMENTUM_FRACTION = 0.8
"""End a burn once the wheel momentum reaches this fraction of its limit."""


class ReactiveStrategy(Strategy):
    """Fires, cools, and heats based on the latest telemetry."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        self.brief = brief
        parameters = brief.nominal_parameters
        limits = brief.limits
        self.thrusters = {
            PropulsionMode.THRUSTER_1: parameters.thruster_1,
            PropulsionMode.THRUSTER_2: parameters.thruster_2,
        }
        # Acceleration estimates start from the nominal model and are refined from telemetry.
        self.acceleration_mps2 = {mode: thruster.acceleration_mps2 for mode, thruster in self.thrusters.items()}
        self.hot_c = limits.max_propulsion_temperature_c - HOT_MARGIN_C
        self.resume_c = self.hot_c - COOLING_BAND_C
        self.heater_on_c = limits.min_propulsion_temperature_c + HEATER_ON_MARGIN_C
        self.heater_off_c = limits.min_propulsion_temperature_c + 2 * HEATER_ON_MARGIN_C
        self.momentum_margin_nms = MOMENTUM_FRACTION * limits.max_abs_wheel_momentum_nms
        self.cooling = False
        self.planned_stop: list[CommandId] = []
        self.decide(telemetry, commander)

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        self.learn(telemetry)
        self.decide(telemetry, commander)

    def learn(self, telemetry: Telemetry) -> None:
        """Estimate the acceleration of a thruster that fired during the whole last decision period."""
        mode = telemetry.propulsion_mode
        if mode is not OFF and mode is self.last_mode:
            elapsed_s = telemetry.time_s - self.last_time_s
            self.acceleration_mps2[mode] = (telemetry.delta_v_mps - self.last_delta_v_mps) / elapsed_s

    def decide(self, telemetry: Telemetry, commander: Commander) -> None:
        mode = telemetry.propulsion_mode
        temperature_c = telemetry.propulsion_temperature_c

        if telemetry.delta_v_mps >= self.brief.target_delta_v_mps:
            commander.execute(SetPropulsionMode(OFF))
            commander.execute(CompleteMission())
            return

        # Temperature hysteresis: stop firing when hot, resume once cooled down.
        if temperature_c >= self.hot_c:
            self.cooling = True
        elif temperature_c <= self.resume_c:
            self.cooling = False

        if mode is not OFF and self.cooling:
            # The planned stop is still in the future, but the thruster must stop now.
            self.cancel_planned_stop(commander)
            commander.execute(SetPropulsionMode(OFF))
            mode = OFF
        elif mode is not OFF:
            # Keep firing; refresh the planned stop with the latest acceleration estimate.
            self.plan_stop(mode, telemetry, commander)
        elif not self.cooling:
            mode = self.thruster_toward_zero(telemetry.wheel_momentum_nms)
            commander.execute(SetPropulsionMode(mode))
            self.plan_stop(mode, telemetry, commander)

        # Heater hysteresis: keep the propulsion system warm while it is idle.
        if not telemetry.heater_on and mode is OFF and temperature_c <= self.heater_on_c:
            commander.execute(SetHeater(True))
        elif telemetry.heater_on and (mode is not OFF or temperature_c >= self.heater_off_c):
            commander.execute(SetHeater(False))

        self.last_mode = mode
        self.last_time_s = telemetry.time_s
        self.last_delta_v_mps = telemetry.delta_v_mps

    def thruster_toward_zero(self, momentum_nms: float) -> PropulsionMode:
        """The thruster whose wheel-momentum rate drives `momentum_nms` toward zero."""
        for mode, thruster in self.thrusters.items():
            if momentum_nms * thruster.wheel_momentum_rate_nms_per_s <= 0:
                return mode
        raise AssertionError("no thruster reduces the wheel momentum")

    def plan_stop(self, mode: PropulsionMode, telemetry: Telemetry, commander: Commander) -> None:
        """Schedule the end of the current burn, replacing any stop planned before."""
        self.cancel_planned_stop(commander)
        rate = self.thrusters[mode].wheel_momentum_rate_nms_per_s
        direction = 1.0 if rate > 0 else -1.0
        momentum_s = (self.momentum_margin_nms - direction * telemetry.wheel_momentum_nms) / abs(rate)
        remaining_mps = self.brief.target_delta_v_mps - telemetry.delta_v_mps
        goal_s = remaining_mps / self.acceleration_mps2[mode]

        stop_s = commander.now_s + max(0.0, min(momentum_s, goal_s))
        self.planned_stop = [commander.schedule(stop_s, SetPropulsionMode(OFF))]
        if goal_s <= momentum_s:
            self.planned_stop.append(commander.schedule(stop_s, CompleteMission()))

    def cancel_planned_stop(self, commander: Commander) -> None:
        for command_id in self.planned_stop:
            commander.cancel(command_id)
        self.planned_stop = []
