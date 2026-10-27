# 評価

[English](evaluation.md) | **日本語**

このページでは，実行ごとの評価指標（`spacecraft_ops_challenge.evaluation`）について説明します。
評価指標は，テレメトリではなく，`RunResult` に含まれる真値から計算されます。

```python
from spacecraft_ops_challenge.evaluation import evaluate
from spacecraft_ops_challenge.simulation import run

result = run(MyStrategy(), scenario)
metrics = evaluate(result)
print(metrics.completion_declared, metrics.safe, metrics.delta_v_error_mps)
```

## 評価指標

`evaluate(result)` は，作成後に変更できない `RunMetrics` を返します。

| フィールド | 意味 |
|---|---|
| `termination_reason` | シミュレーションの `TerminationReason` |
| `end_time_s` | 終了時刻 |
| `completion_declared` | 終了理由が `COMPLETION_DECLARED` なら `True`，それ以外なら `False` |
| `safe` | 安全制約の違反が1つもなければ `True`，あれば `False` |
| `safety_violations` | `SafetyViolation` のタプル |
| `target_delta_v_mps` | シナリオの目標 Δv |
| `delta_v_mps` | シミュレーション終了時の真の Δv |
| `delta_v_error_mps` | 得られた Δv から目標 Δv を引いた値（正なら目標を超過） |
| `completion_declared_time_s` | 完了が宣言された場合はその終了時刻，そうでなければ `None` |
| `time_limit_s` | シナリオの制限時間 |
| `decision_period_s` | シナリオの判断周期 |
| `nominal_battery_capacity_wh` | 公開された公称モデルのバッテリ容量（実際の宇宙機はこれと異なる場合がある） |
| `min_battery_energy_limit_wh` | バッテリ蓄電量の安全制約 |
| `min_battery_energy_wh` | 真のバッテリ蓄電量の最小値 |
| `min_propulsion_temperature_c` | 真の推進系温度の最小値 |
| `max_propulsion_temperature_c` | 真の推進系温度の最大値 |
| `max_abs_wheel_momentum_nms` | 真のホイール角運動量の絶対値の最大値 |

完了を宣言したからといって，成功したことにはなりません。
戦略は，Δv がまったく得られていない段階でも，いつでも完了を宣言できます。
そのため，結果の良し悪しは `safe` や `delta_v_error_mps` などのフィールドから判断してください。
たとえば時刻0で完了を宣言すると，`completion_declared=True` となり，`delta_v_error_mps` は目標値の符号を反転させた値になります。

最小値と最大値は，`trajectory` に含まれる真の状態と `final_state` から求めます。

## シリアライズ

`metrics.to_dict()` は，`json.dumps` に渡せる辞書を返します。
キーは上記のフィールド名です。
終了理由はその文字列値で表され，安全制約の各違反は `reason`，`time_s`，`message` を持つ辞書で表されます。
