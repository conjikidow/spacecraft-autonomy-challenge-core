# Reference Scenarios

`spacecraft_ops.reference` provides public reference scenarios for the toy spacecraft model.
All numbers are placeholders for a toy model, chosen so that every safety limit matters for a plausible plan.

```python
from spacecraft_ops.reference import reference_scenario, reference_scenario_names

print(reference_scenario_names())
scenario = reference_scenario("nominal")
```

`reference_scenario(name)` builds a new `Scenario` and raises `KeyError` listing the available names for an unknown name.
`nominal_parameters()`, `nominal_limits()`, and `nominal_initial_state()` return the shared configuration.

## Shared Configuration

All reference scenarios use the same nominal model, limits, initial state, and timing.

| Quantity | Value |
|---|---|
| Thruster acceleration | 0.001 m/s² (both thrusters) |
| Thruster power | 30 W (both thrusters) |
| Thruster heat | 40 W (both thrusters) |
| Wheel-momentum rate | +0.002 Nms/s (`THRUSTER_1`), −0.002 Nms/s (`THRUSTER_2`) |
| Power generation | 60 W |
| Bus load | 40 W |
| Heater power | 10 W |
| Battery capacity | 100 Wh |
| Heat capacity | 2000 J/K |
| Thermal conductance | 0.5 W/K |
| Sink temperature | −10 °C |
| Initial temperature | 20 °C |
| Initial battery energy | 80 Wh |
| Initial wheel momentum | 0 Nms |
| Initial heater and propulsion | off |
| Propulsion temperature limits | 0 °C to 60 °C |
| Minimum battery energy | 10 Wh |
| Maximum absolute wheel momentum | 5 Nms |
| Target delta-v | 10 m/s |
| Time limit | 21600 s |
| Integration step | 1 s |
| Decision period | 60 s |

## Binding Constraints

The goal needs 10000 s of firing, so the limits shape any plan that reaches it:

- Wheel momentum: one thruster alone reaches the 5 Nms limit after 2500 s, so a plan must alternate thrusters.
- Overheating: while firing, the temperature approaches −10 + 40 / 0.5 = 70 °C
  with a time constant of 2000 / 0.5 = 4000 s.
  Starting at 20 °C it passes 60 °C after about 6400 s of continuous firing, so a plan must pause to cool down.
- Undercooling: while idle with the heater off, the temperature approaches the −10 °C sink
  and passes 0 °C after about 4400 s.
  With the heater on, it approaches 10 °C instead.
- Battery: firing drains 10 W and firing with the heater on drains 20 W, against 70 Wh of usable energy at the start.

A plan that alternates thrusters and pauses to cool completes in roughly 13000 s, well within the time limit.

## Scenarios

### `nominal`

The spacecraft behaves exactly as the nominal model.
There are no modifiers.

### `thruster-degradation`

Identical to `nominal`, plus one modifier: `ThrusterEfficiency(THRUSTER_1, factor=0.8, onset_time_s=3600.0)`.
From 3600 s onward, `THRUSTER_1` delivers 80 % of its nominal acceleration.
Its power, heat, and wheel-momentum rate are unchanged.
The mission brief still shows the nominal parameters, so a strategy can only notice the change through telemetry.
