# Spacecraft Model

**English** | [日本語](spacecraft-model.ja.md)

This page describes the reference spacecraft model in `spacecraft_ops_challenge.model`,
telemetry in `spacecraft_ops_challenge.telemetry`, and modifiers in `spacecraft_ops_challenge.modifiers`.

The model is a deliberately small toy model.
All numbers are parameters; none are fixed by the model itself.
Units are part of every field name:
`_s` (seconds), `_mps` (meters per second), `_mps2` (meters per second squared), `_c` (degrees Celsius),
`_w` (watts), `_wh` (watt-hours), `_j_per_k` (joules per kelvin), `_w_per_k` (watts per kelvin), and `_nms` (newton-meter-seconds).

## State

`SpacecraftState` is the true internal state:

| Field | Meaning |
|---|---|
| `time_s` | Simulation time |
| `delta_v_mps` | Accumulated delta-v |
| `propulsion_temperature_c` | Temperature of the propulsion system |
| `battery_energy_wh` | Stored battery energy |
| `wheel_momentum_nms` | Scalar wheel momentum |
| `heater_on` | Heater state |
| `propulsion_mode` | `OFF`, `THRUSTER_1`, or `THRUSTER_2` |

## Parameters

`SpacecraftParameters` holds one `ThrusterParameters` per thruster and the spacecraft-level parameters.

Each thruster has an acceleration (delta-v rate), an electrical load,
a heat input to the propulsion system, and a signed wheel-momentum rate.
Both thrusters are configured independently.
A symmetric configuration uses identical values except for opposite wheel-momentum rates,
so that `THRUSTER_1` increases and `THRUSTER_2` decreases the wheel momentum.

`min_firing_temperature_c` is the lowest propulsion temperature at which a selected thruster fires.

`SafetyLimits` defines the maximum propulsion temperature, the minimum battery energy, and the maximum absolute wheel momentum.

## Dynamics

`compute_rates(state, parameters)` returns the time derivatives in `StateRates`.
Only the thruster selected by the propulsion mode contributes,
and only while the propulsion temperature is at or above `min_firing_temperature_c`.
Below that temperature the selected thruster contributes no acceleration, electrical load, heat, or wheel-momentum rate,
as if propulsion were off.
The propulsion mode itself stays as commanded, so telemetry still reports it.

Delta-v and momentum:

```text
d(delta_v)/dt = thruster acceleration
dH/dt         = thruster wheel-momentum rate
```

Power, with heater and thruster loads counted only while active:

```text
P_net = power_generation - bus_load - heater_load - thruster_load
```

Thermal, as a single lumped node with heat capacity `C`, conductance `G`, and sink temperature `T_sink`:

```text
C * dT/dt = heater_power + thruster_heat - G * (T - T_sink)
```

All heater electrical power becomes heat in the propulsion system.

`integrate(state, rates, duration_s, parameters)` advances the state by one explicit Euler step.
Battery energy is converted from watts to watt-hours and capped at the battery capacity.
It is not clamped at zero.

## Telemetry

`Telemetry` is the observation available to a strategy.
It has the same fields as `SpacecraftState` but is a separate type, and its values may differ from the true state.
`nominal_telemetry(state)` returns an ideal observation of the true state.

## Modifiers

A `Modifier` changes the behavior of a run relative to the nominal model.
It can override any of three hooks; the defaults change nothing:

| Hook | Changes |
|---|---|
| `modify_parameters(parameters, state, rng)` | The effective parameters at `state.time_s` |
| `modify_rates(rates, state, parameters, rng)` | The state rates after the nominal model |
| `modify_telemetry(telemetry, state, rng)` | The observation given to a strategy |

Hooks receive the true state, so effects can depend on time or on the state.
Modifiers are applied in order, each receiving the result of the previous one.
They should be stateless and must take any randomness from the provided seeded `random.Random`.

`effective_parameters`, `effective_rates`, and `observe` apply a sequence of modifiers.

Built-in modifiers:

| Modifier | Effect |
|---|---|
| `ThrusterEfficiency(thruster, factor, onset_time_s=0.0)` | Scales one thruster's acceleration by `factor` from `onset_time_s` onward |
| `TelemetryBias(channel, bias)` | Adds a constant to one numeric telemetry channel |
