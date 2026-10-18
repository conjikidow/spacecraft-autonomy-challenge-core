"""A small toy problem for trying the strategy API, deliberately different from the challenge problem.

Its limits are loose, so no strategy runs into them; the examples only show how the API behaves.
"""

from spacecraft_ops import PropulsionMode, SafetyLimits, SpacecraftParameters, Strategy, ThrusterParameters
from spacecraft_ops.evaluation import evaluate
from spacecraft_ops.model import SpacecraftState
from spacecraft_ops.problem import Problem
from spacecraft_ops.results import RunResult
from spacecraft_ops.scenario import Scenario
from spacecraft_ops.simulation import run


def toy_scenario() -> Scenario:
    """A short toy scenario: reach 1 m/s within 600 s, with updates every 30 s."""
    thruster = ThrusterParameters(acceleration_mps2=0.01, power_w=1.0, heat_w=1.0, wheel_momentum_rate_nms_per_s=0.001)
    problem = Problem(
        parameters=SpacecraftParameters(
            thruster_1=thruster,
            thruster_2=ThrusterParameters(
                acceleration_mps2=0.01, power_w=1.0, heat_w=1.0, wheel_momentum_rate_nms_per_s=-0.001
            ),
            power_generation_w=10.0,
            bus_load_w=1.0,
            heater_power_w=1.0,
            battery_capacity_wh=100.0,
            heat_capacity_j_per_k=1000.0,
            thermal_conductance_w_per_k=1.0,
            sink_temperature_c=20.0,
        ),
        initial_state=SpacecraftState(
            time_s=0.0,
            delta_v_mps=0.0,
            propulsion_temperature_c=20.0,
            battery_energy_wh=50.0,
            wheel_momentum_nms=0.0,
            heater_on=False,
            propulsion_mode=PropulsionMode.OFF,
        ),
        limits=SafetyLimits(
            min_propulsion_temperature_c=-100.0,
            max_propulsion_temperature_c=200.0,
            min_battery_energy_wh=0.0,
            max_abs_wheel_momentum_nms=100.0,
        ),
        target_delta_v_mps=1.0,
        time_limit_s=600.0,
        decision_period_s=30.0,
    )
    return Scenario(name="toy", problem=problem, description="Toy problem for the API examples.")


def run_and_report(strategy: Strategy) -> RunResult:
    """Run `strategy` on the toy scenario and print what happened."""
    result = run(strategy, toy_scenario())
    metrics = evaluate(result)
    for scheduled in result.executed_commands:
        print(f"{scheduled.time_s:7.1f} s  #{scheduled.command_id}  {scheduled.command}")
    print(f"termination: {metrics.termination_reason} at {metrics.end_time_s:.1f} s")
    print(f"true delta-v: {metrics.delta_v_mps:.3f} m/s (target {metrics.target_delta_v_mps:.3f} m/s)")
    return result
