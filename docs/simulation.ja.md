# シミュレーション

[English](simulation.md) | **日本語**

このページでは，問題（`spacecraft_autonomy_challenge.problem`），シナリオ（`spacecraft_autonomy_challenge.scenario`），シミュレーション設定（`spacecraft_autonomy_challenge.config`），シミュレーション（`spacecraft_autonomy_challenge.simulation`），実行結果（`spacecraft_autonomy_challenge.results`）について説明します。

## 問題

`Problem` は，その問題に属するすべてのシナリオが共有する固定の課題です。

| フィールド | 意味 |
|---|---|
| `parameters` | 公開される公称の `SpacecraftParameters` |
| `initial_state` | 時刻0における `SpacecraftState` |
| `limits` | `SafetyLimits` |
| `target_delta_v_mps` | 目標 Δv |
| `time_limit_s` | シミュレーションが終了する時刻 |
| `decision_period_s` | 戦略の `update` が呼ばれる周期 |

`problem.brief()` は，戦略に渡される `MissionBrief` を返します。

## シナリオ

`Scenario` は，問題のバリエーションの1つです。

| フィールド | 意味 |
|---|---|
| `name`，`description` | 識別情報 |
| `problem` | 対象の `Problem` |
| `modifiers` | シミュレーション中に適用される `Modifier` の列 |
| `seed` | シミュレーションで使う乱数生成器のシード |

`Modifier` のないシナリオは，公称モデルとまったく同じように振る舞います。
`scenario.brief()` は，そのシナリオが属する問題の `MissionBrief` を返します。
そのため，同じ問題に属するシナリオは，戦略からはどれも同じに見えます。

## シミュレーション設定

`SimulationConfig` は，数値精度だけに影響する設定を保持します。
唯一のフィールドである `integration_step_s` は陽的オイラー法による積分の最大刻み幅で，デフォルトは1秒です。
この設定が戦略から見えることはありません。

## 戦略の実行

```python
from spacecraft_autonomy_challenge.simulation import run

result = run(MyStrategy(), scenario)
print(result.termination.reason, result.final_state.delta_v_mps)
```

`run(strategy, scenario, *, config=None, seed=None)` は，`config` が `None` ならデフォルトの `SimulationConfig` を使い，
`seed` が与えられればシナリオのシードを上書きします。
戦略が送出した `Exception` は `run` の外には伝播せず，代わりにシミュレーションを終了させます。

## 時間

次の3つの時間スケールは互いに独立しています。

- 積分刻み：陽的オイラー法による積分の最大刻み幅
- 判断周期：`update` が呼ばれる間隔
- コマンド時刻：戦略が選ぶ任意の時刻

積分器はコマンド時刻と判断時刻で刻みを分割するため，コマンドはスケジュールされた時刻ちょうどに反映されます。
積分の格子点，判断時刻，制限時間は小さな許容誤差を考慮して比較されるため，`3 * 0.1` のように刻み幅や判断周期の倍数を計算したときに浮動小数点誤差が生じても，判断時刻が飛ばされることはありません。

## イベントの順序

シミュレーションは，各イベント時刻 `t` で次の処理を行います。

1. `Modifier` の `modify_parameters` フックと `modify_rates` フックを適用しながら，真の状態を `t` まで積分します。
2. 真の状態が安全制約を満たしているかを検査し，違反があればシミュレーションを終了します。
3. `t` にスケジュールされた実行待ちのコマンドをタイムラインの順に実行し，`DeclareCompletion` が実行されたらシミュレーションを終了します。
4. 判断時刻であれば，`Modifier` の `modify_telemetry` フックを通してテレメトリを取得し，
   `update` を呼び出して，そこで `t` に登録されたコマンドを実行します。
5. `t` が制限時間に達していれば，シミュレーションを `TIME_LIMIT` で終了します。
   その場合でも，制限時間ちょうどにスケジュールされたコマンドは実行され，その時刻の判断も行われます。
   制限時間より後にスケジュールされたコマンドが実行されることはありません。

次のイベント時刻は，次の積分刻みの時刻，次の判断時刻，次の実行待ちコマンドの時刻，制限時間のうち，最も早い時刻です。

時刻0では，初期状態を検査し，テレメトリを取得し，`initialize` を呼び出してから，即時実行のコマンドを実行します。

## 終了条件

| `TerminationReason` | 原因 |
|---|---|
| `COMPLETION_DECLARED` | `DeclareCompletion` コマンドが実行された。戦略が完了を宣言したというだけで，成功を意味するわけではない |
| `TIME_LIMIT` | 制限時間に達した |
| `THERMAL_VIOLATION` | 推進系温度が上限を超えた |
| `BATTERY_DEPLETED` | バッテリの蓄電量が下限を下回った |
| `MOMENTUM_VIOLATION` | ホイール角運動量の絶対値が上限を超えた |
| `STRATEGY_ERROR` | 戦略が例外を送出した |
| `INVALID_COMMAND` | 戦略が `CommandError` を捕捉せずに送出した |

複数の安全制約に同時に違反した場合は，すべての違反が記録され，終了理由はこの表の順序に従って決まります。

## 実行結果

`RunResult` には次のものが含まれます。

- `scenario`，`config`，`seed`
- `termination`：終了理由，時刻，詳細（メッセージまたはトレースバック）
- `safety_violations`
- `final_state`
- `trajectory`：時刻0と各イベント時刻における真の状態（積分の後，コマンドの実行前に記録）
- `telemetry`：戦略に渡されたすべてのテレメトリ
- `executed_commands`

## ステップ実行インタフェース

`Simulation` は，`run` 以外のドライバのために，同じループを明示的なステップとして提供します。

```python
from spacecraft_autonomy_challenge.config import SimulationConfig
from spacecraft_autonomy_challenge.simulation import Simulation

simulation = Simulation(scenario, config=SimulationConfig(), seed=0)
telemetry = simulation.start()
with simulation.decision() as commander:
    commander.execute(command)
while (telemetry := simulation.advance()) is not None:
    with simulation.decision() as commander:
        ...
result = simulation.result()
```

- `start()` は時刻0のテレメトリを返します。
  初期状態が制約に違反している場合は `None` を返します。
- `decision()` は現在時刻でコマンドを発行するためのウィンドウを開き，`LocalCommander` を渡します。
  現在時刻にスケジュールされたコマンドは，ウィンドウが閉じたときに実行されます。
  ウィンドウが例外によって終了した場合は，代わりに次の `advance()` の冒頭で実行されます。
- `advance()` は次の判断時刻まで進めて，そのテレメトリを返します。
  シミュレーションが終了した後は `None` を返します。
- `abort(reason, detail)` は，戦略のエラーの後などに，外部からシミュレーションを終了させます。
- `result()` は，シミュレーションの終了後に `RunResult` を返します。
