# Challenge Problem

**English** | [日本語](challenge.ja.md)

`spacecraft_autonomy_challenge.challenge` defines the challenge problem and its public scenarios.
All numbers are for the toy spacecraft model described in [Spacecraft Model](spacecraft-model.md).

```python
from spacecraft_autonomy_challenge.challenge import problem, scenario, scenario_names

print(scenario_names())
nominal = scenario("nominal")
```

`problem()` returns the `Problem` shared by every scenario.
Its time limit is also available as `TIME_LIMIT_S`.
`scenario(name)` builds a new `Scenario` and raises `KeyError` listing the available names for an unknown name.

## Problem

| Quantity | Value |
|---|---|
| Target delta-v | 10 m/s |
| Time limit | 21320 s |
| Decision period | 60 s |
| Thruster acceleration | 0.001 m/s² (both thrusters) |
| Thruster power | 30 W (both thrusters) |
| Thruster heat | 40 W (both thrusters) |
| Wheel-momentum rate | +0.002 Nms/s (`THRUSTER_1`), −0.002 Nms/s (`THRUSTER_2`) |
| Momentum dump rate | 0.005 Nms/s |
| Momentum dump power | 30 W |
| Momentum dump heat | 12 W |
| Power generation | 60 W |
| Bus load | 40 W |
| Heater power | 10 W |
| Battery capacity | 100 Wh |
| Heat capacity | 2000 J/K |
| Thermal conductance | 0.5 W/K |
| Sink temperature | −10 °C |
| Minimum firing temperature | 0 °C |
| Maximum propulsion temperature | 60 °C |
| Minimum battery energy | 10 Wh |
| Maximum absolute wheel momentum | 5 Nms |
| Initial temperature | 20 °C |
| Initial battery energy | 80 Wh |
| Initial delta-v and wheel momentum | 0 |
| Initial heater, propulsion, and momentum dump | off |

## Scenarios

### `nominal`

The spacecraft behaves exactly as the nominal model.
There are no modifiers.

### `thruster-degradation`

Identical to `nominal`, plus one modifier: `ThrusterEfficiency(THRUSTER_1, factor=0.8, onset_time_s=3600.0)`.
From 3600 s onward, `THRUSTER_1` delivers 80 % of its nominal acceleration and wheel-momentum rate.
Its power and heat are unchanged.
The mission brief still shows the nominal parameters, so a strategy can only notice the change through telemetry.

### `delta-v-sensor-bias`

Identical to `nominal`, plus one modifier: `TelemetryBias("delta_v_mps", bias=0.3, onset_time_s=3000.0)`.
From 3000 s onward, the delta-v reading is 0.3 m/s above the true delta-v.
The true state is unchanged, and the safety limits and the metrics use the true state.
