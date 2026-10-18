"""Open-loop example: plan the whole maneuver in `initialize` and never look at telemetry again.

The plan is predicted from the published nominal model in the mission brief.
It fires one thruster at a time, alternating between them to keep the wheel momentum bounded,
and pauses to cool down whenever the predicted temperature gets close to its limit.
Because it never reacts, any deviation from the nominal model goes unnoticed.
"""

import math

from spacecraft_ops import (
    Commander,
    CompleteMission,
    MissionBrief,
    PropulsionMode,
    SetPropulsionMode,
    SpacecraftParameters,
    Strategy,
    Telemetry,
    ThrusterParameters,
)

HOT_MARGIN_C = 8.0
"""Stop firing this far below the maximum temperature."""
COOLING_BAND_C = 10.0
"""Cool down by this much before firing again."""
MOMENTUM_FRACTION = 0.8
"""Switch thrusters once the wheel momentum reaches this fraction of its limit."""


def thermal_equilibrium_c(parameters: SpacecraftParameters, heat_w: float) -> float:
    """Temperature at which passive cooling balances `heat_w`."""
    return parameters.sink_temperature_c + heat_w / parameters.thermal_conductance_w_per_k


def temperature_after(start_c: float, duration_s: float, equilibrium_c: float, time_constant_s: float) -> float:
    """Exact solution of the lumped thermal model: exponential approach toward the equilibrium."""
    return equilibrium_c + (start_c - equilibrium_c) * math.exp(-duration_s / time_constant_s)


def time_to_reach(start_c: float, target_c: float, equilibrium_c: float, time_constant_s: float) -> float:
    """Time until the temperature reaches `target_c`, or infinity if it never does."""
    ratio = (target_c - equilibrium_c) / (start_c - equilibrium_c) if start_c != equilibrium_c else 0.0
    if not 0.0 < ratio <= 1.0:
        return math.inf
    return -time_constant_s * math.log(ratio)


def thruster_toward_zero(
    parameters: SpacecraftParameters, momentum_nms: float
) -> tuple[PropulsionMode, ThrusterParameters]:
    """The thruster whose wheel-momentum rate drives `momentum_nms` toward zero."""
    if momentum_nms * parameters.thruster_1.wheel_momentum_rate_nms_per_s <= 0:
        return PropulsionMode.THRUSTER_1, parameters.thruster_1
    return PropulsionMode.THRUSTER_2, parameters.thruster_2


class FixedSequenceStrategy(Strategy):
    """Schedules a complete command sequence at time 0 and does nothing afterward."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        parameters = brief.nominal_parameters
        time_constant_s = parameters.heat_capacity_j_per_k / parameters.thermal_conductance_w_per_k
        hot_c = brief.limits.max_propulsion_temperature_c - HOT_MARGIN_C
        resume_c = hot_c - COOLING_BAND_C
        momentum_margin_nms = MOMENTUM_FRACTION * brief.limits.max_abs_wheel_momentum_nms

        # Predicted state, advanced burn by burn with the nominal model.
        time_s = telemetry.time_s
        temperature_c = telemetry.propulsion_temperature_c
        momentum_nms = telemetry.wheel_momentum_nms
        remaining_mps = brief.target_delta_v_mps - telemetry.delta_v_mps

        while remaining_mps > 1e-9:
            mode, thruster = thruster_toward_zero(parameters, momentum_nms)
            rate = thruster.wheel_momentum_rate_nms_per_s
            heating_c = thermal_equilibrium_c(parameters, thruster.heat_w)

            # A burn ends at whichever comes first: the goal, the momentum margin, or the hot threshold.
            goal_s = remaining_mps / thruster.acceleration_mps2
            momentum_s = (momentum_margin_nms - momentum_nms * math.copysign(1.0, rate)) / abs(rate)
            thermal_s = time_to_reach(temperature_c, hot_c, heating_c, time_constant_s)
            burn_s = max(0.0, min(goal_s, momentum_s, thermal_s))

            commander.schedule(time_s, SetPropulsionMode(mode))
            time_s += burn_s
            remaining_mps -= burn_s * thruster.acceleration_mps2
            momentum_nms += burn_s * rate
            temperature_c = temperature_after(temperature_c, burn_s, heating_c, time_constant_s)

            # Too hot to continue: switch off and wait for passive cooling. The pause ends well above the
            # minimum temperature, so the heater is not needed. After a momentum-limited burn the other
            # thruster starts immediately; selecting it implicitly stops the current one.
            if burn_s == thermal_s and burn_s < goal_s:
                commander.schedule(time_s, SetPropulsionMode(PropulsionMode.OFF))
                cooling_c = thermal_equilibrium_c(parameters, 0.0)
                time_s += time_to_reach(temperature_c, resume_c, cooling_c, time_constant_s)
                temperature_c = resume_c

        commander.schedule(time_s, SetPropulsionMode(PropulsionMode.OFF))
        commander.schedule(time_s, CompleteMission())
