# Evaluation

This page describes per-run evaluation metrics (`spacecraft_ops_challenge.evaluation`).
Metrics are computed from the ground truth in a `RunResult`, not from telemetry.

```python
from spacecraft_ops_challenge.evaluation import evaluate
from spacecraft_ops_challenge.simulation import run

result = run(MyStrategy(), scenario)
metrics = evaluate(result)
print(metrics.completion_declared, metrics.safe, metrics.delta_v_error_mps)
```

## Metrics

`evaluate(result)` returns a frozen `RunMetrics`:

| Field | Meaning |
|---|---|
| `termination_reason` | `TerminationReason` of the run |
| `end_time_s` | Termination time |
| `completion_declared` | `True` if and only if the reason is `COMPLETION_DECLARED` |
| `safe` | `True` if and only if there are no safety violations |
| `safety_violations` | Tuple of `SafetyViolation` |
| `target_delta_v_mps` | Delta-v goal of the scenario |
| `delta_v_mps` | True delta-v at the end of the run |
| `delta_v_error_mps` | Achieved minus target delta-v, so positive means overshoot |
| `completion_declared_time_s` | Termination time if completion was declared, otherwise `None` |
| `time_limit_s` | Time limit of the scenario |
| `min_battery_energy_wh` | Lowest true battery energy |
| `min_propulsion_temperature_c` | Lowest true propulsion temperature |
| `max_propulsion_temperature_c` | Highest true propulsion temperature |
| `max_abs_wheel_momentum_nms` | Largest absolute true wheel momentum |

Declaring completion is not success.
A strategy can declare completion at any time, even before any delta-v is achieved,
so judge an outcome from fields such as `safe` and `delta_v_error_mps`.
For example, declaring completion at time 0 gives `completion_declared=True`
and `delta_v_error_mps` equal to minus the target.

The extremes are taken over the true states in `trajectory` and over `final_state`.

## Serialization

`metrics.to_dict()` returns a dictionary that `json.dumps` accepts.
The keys are the field names above.
The termination reason is its string value, and each safety violation is a dictionary with `reason`, `time_s`, and `message`.
