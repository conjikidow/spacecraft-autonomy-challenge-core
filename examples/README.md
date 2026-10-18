# Examples

Two example strategies for the challenge scenarios in `spacecraft_ops.challenge`.
Both import only from the top-level `spacecraft_ops` package and see nothing but the mission brief and telemetry.

## `fixed_sequence.py`

`FixedSequenceStrategy` is an open-loop strategy.
In `initialize` it predicts the whole maneuver with the nominal model from the mission brief
and schedules every command at once.
The plan alternates thrusters to keep the wheel momentum bounded, pauses to cool down before the temperature limit,
and ends with `DeclareCompletion`.
It does not override `update`, so it never reacts to telemetry.

It reaches the target on `nominal` exactly, but on `thruster-degradation` it ends short of the target,
because it cannot notice the weaker thruster.

## `reactive.py`

`ReactiveStrategy` is a closed-loop strategy that decides from telemetry at every update:

- It stops firing near the maximum temperature and resumes after cooling down (temperature hysteresis).
- It starts the thruster that drives the wheel momentum toward zero.
- It switches the heater on when idle near the minimum temperature.
- It estimates each thruster's acceleration from the delta-v telemetry.
- It sends `DeclareCompletion` once the delta-v telemetry reaches the target.

When a burn starts, it schedules a future stop for the time the wheel momentum would reach a margin below its limit,
or for the time the target would be reached together with `DeclareCompletion`.
It cancels that pending stop when the temperature forces an earlier stop,
and replaces it at every update with one based on the latest estimates.
This lets it reach the target on both `nominal` and `thruster-degradation`.

## Running an Example

From the repository root, run an example with the `spacecraft-ops` command:

```sh
uv run spacecraft-ops run examples/fixed_sequence.py:FixedSequenceStrategy
uv run spacecraft-ops run examples/reactive.py:ReactiveStrategy --scenario thruster-degradation
```

The example files are not part of the installed package.
To run one from Python, load it by path, for example from the repository root:

```python
import importlib.util

from spacecraft_ops.challenge import scenario
from spacecraft_ops.simulation import run

spec = importlib.util.spec_from_file_location("reactive", "examples/reactive.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

result = run(module.ReactiveStrategy(), scenario("thruster-degradation"))
print(result.termination.reason, result.termination.time_s, result.final_state.delta_v_mps)
```

Save this as a script and run it with `uv run python <script>`.
