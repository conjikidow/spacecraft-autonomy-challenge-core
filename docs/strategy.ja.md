# 戦略の書き方

[English](strategy.md) | **日本語**

戦略は，タイムラインにコマンドをスケジュールすることで宇宙機を運用します。
戦略が受け取るのは `MissionBrief`，`Telemetry`，`Commander` だけであり，宇宙機の真の状態を見ることはありません。
これらはすべて，トップレベルの `spacecraft_autonomy_challenge` パッケージからエクスポートされています。

```python
from spacecraft_autonomy_challenge import Commander, MissionBrief, SetHeater, Strategy, Telemetry


class MyStrategy(Strategy):
    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        self.heater_command = commander.schedule(600.0, SetHeater(on=True))

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        print(telemetry.time_s, telemetry.heater_on)
        if telemetry.time_s >= 300.0:
            commander.cancel(self.heater_command)
```

## ライフサイクル

1. `initialize(brief, telemetry, commander)` は，シミュレーション時刻0に一度だけ呼ばれます。
2. `update(telemetry, commander)` は，シミュレーションが終了するまで，
   `k >= 1` の各判断時刻 `k * brief.decision_period_s` に呼ばれます。

どちらのコールバックも省略できます。
決まったコマンド列に従う戦略なら，`initialize` で列全体をスケジュールし，`update` は空のままにしておけます。
スケジュールされたコマンドは，それ以上コールバックが呼ばれなくても，それぞれの時刻に実行されます。
適応的な戦略は，`update` の中でコマンドをスケジュールしたりキャンセルしたりできます。

## `MissionBrief`

`MissionBrief` には，目標 Δv，制限時間，判断周期，`SafetyLimits`，公称の `SpacecraftParameters`（`nominal_parameters`），
公称の初期状態を理想的に観測した `Telemetry`（`nominal_initial_telemetry`）が含まれます。
実際の宇宙機は公称パラメータや公称の初期状態からずれていることがあり，テレメトリも真の状態からずれていることがあります。
戦略がそうしたずれを推定する手がかりは，テレメトリしかありません。

## `Commander`

`Commander` はインタフェース（`typing.Protocol`）です。
戦略は，以下に挙げるメンバだけに依存するようにしてください。
シミュレーションが渡すのは `spacecraft_autonomy_challenge.simulation.LocalCommander` で，これは同じプロセス内でタイムラインを直接操作します。
要求と結果はすべて，時刻，コマンド，コマンド識別子，`ScheduledCommand` の値といった単純なデータで表されます。

| メンバ | 振る舞い |
|---|---|
| `now_s` | 現在のシミュレーション時刻（秒） |
| `schedule(time_s, command)` | コマンドを `time_s`（`now_s` 以降）に登録し，その `CommandId` を返す |
| `execute(command)` | `schedule(now_s, command)` と同じ |
| `cancel(command_id)` | 実行待ちのコマンドをキャンセルし，それが実行待ちだったかどうかを返す |
| `cancel_from(time_s)` | `time_s` 以降の実行待ちのコマンドをすべてキャンセルし，それらの識別子を返す |
| `pending()` | 実行待ちのコマンドを実行順に返す |

`cancel_from(now_s)` を呼んでから新たに `schedule` を呼ぶと，タイムラインの残りを置き換えられます。

`Commander` が有効なのは，それが渡されたコールバックの間だけです。
後からいずれかのメンバを使うと，`CommandError` が送出されます。
コールバックの実行中にコマンドが実行されることはありません。
`now_s` にスケジュールされたコマンドは，コールバックから戻った直後，シミュレーション時刻が進む前に実行されます。

コマンドの種類と順序規則については [コマンドとタイムライン](timeline.ja.md) を参照してください。

## エラー

- 過去の時刻を指定するなどの不正な要求をすると，`CommandError` が送出されます。
  戦略はこれを捕捉して処理を続けても構いません。
- `CommandError` が捕捉されなかった場合，シミュレーションは `INVALID_COMMAND` で終了します。
- それ以外の例外が捕捉されなかった場合，シミュレーションは `STRATEGY_ERROR` で終了します。
