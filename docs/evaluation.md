# Evaluation

This page describes per-run evaluation metrics (`spacecraft_ops.evaluation`).
Metrics are computed from the ground truth in a `RunResult`, not from telemetry.

```python
from spacecraft_ops.evaluation import evaluate, reference_score
from spacecraft_ops.simulation import run

result = run(MyStrategy(), scenario)
metrics = evaluate(result)
print(metrics.completed, metrics.delta_v_error_mps, reference_score(metrics))
```

## Metrics

`evaluate(result)` returns a frozen `RunMetrics`:

| Field | Meaning |
|---|---|
| `termination_reason` | `TerminationReason` of the run |
| `end_time_s` | Termination time |
| `completed` | `True` if and only if the reason is `MISSION_COMPLETE` |
| `safe` | `True` if and only if there are no safety violations |
| `safety_violations` | Tuple of `SafetyViolation` |
| `target_delta_v_mps` | Delta-v goal of the scenario |
| `delta_v_mps` | True delta-v at the end of the run |
| `delta_v_error_mps` | Achieved minus target delta-v, so positive means overshoot |
| `completion_time_s` | Termination time if completed, otherwise `None` |
| `time_limit_s` | Time limit of the scenario |
| `min_battery_energy_wh` | Lowest true battery energy |
| `min_propulsion_temperature_c` | Lowest true propulsion temperature |
| `max_propulsion_temperature_c` | Highest true propulsion temperature |
| `max_abs_wheel_momentum_nms` | Largest absolute true wheel momentum |

The extremes are taken over the true states in `trajectory` and over `final_state`.

## Serialization

`metrics.to_dict()` returns a dictionary that `json.dumps` accepts.
The keys are the field names above.
The termination reason is its string value, and each safety violation is a dictionary with `reason`, `time_s`, and `message`.

## Reference Score

`reference_score(metrics, weights=ScoreWeights())` is a simple configurable score in [0, 1] for comparing runs locally.
It is 0 unless the run is both completed and safe.
Otherwise it is the weighted mean of two terms:

- accuracy: `max(0, 1 - |delta_v_error_mps| / target_delta_v_mps)`.
  If the target is 0, accuracy is 1 when the error is 0 and 0 otherwise.
- time: `max(0, 1 - completion_time_s / time_limit_s)`.

```text
score = (accuracy_weight * accuracy + time_weight * time) / (accuracy_weight + time_weight)
```

`ScoreWeights(accuracy=0.8, time=0.2)` holds the weights.
Both must be non-negative and their sum must be positive, otherwise `ValueError` is raised.
