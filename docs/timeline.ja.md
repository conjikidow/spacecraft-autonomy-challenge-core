# コマンドとタイムライン

[English](timeline.md) | **日本語**

このページでは，`spacecraft_autonomy_challenge.commands` のコマンドの種類と，`spacecraft_autonomy_challenge.timeline` のタイムラインについて説明します。

## コマンド

| コマンド | 効果 |
|---|---|
| `SetPropulsionMode(mode)` | 推進モードを `PropulsionMode.OFF`，`THRUSTER_1`，`THRUSTER_2` のいずれかに切り替える |
| `SetHeater(on)` | 推進系のヒータをオン（`True`）またはオフ（`False`）にする |
| `SetMomentumDump(on)` | 角運動量ダンプをオン（`True`）またはオフ（`False`）にする |
| `DeclareCompletion()` | 戦略がマヌーバを完了したとみなしたことを宣言し，シミュレーションを終了させる。成功を意味するものではない |

推進モードは排他的で，一方のスラスタを選ぶともう一方は暗黙のうちに停止するため，2つのスラスタが同時に噴射することはありません。
角運動量ダンプがオンの間は，推進モードにかかわらず，どちらのスラスタも噴射しません。
角運動量ダンプは，ホイール角運動量が0になると自らオフになります。
詳しくは[宇宙機モデル](spacecraft-model.ja.md#角運動量ダンプ)を参照してください。

コマンドは，作成後に変更できないデータクラスです。
`SetPropulsionMode` には `"THRUSTER_1"` のようなモード名も渡せます。
`SetHeater` と `SetMomentumDump` は `bool` を取ります。
不正な値を渡すと，`ValueError` のサブクラスである `CommandError` が送出されます。

## タイムライン

`Timeline` は，将来実行するようスケジュールされたコマンドを保持します。
時刻はシミュレーション時刻の秒数で表します。

| メソッド | 振る舞い |
|---|---|
| `schedule(time_s, command, now_s=...)` | `command` を `time_s` に登録し，その `CommandId` を返す |
| `cancel(command_id)` | 実行待ちのコマンドを取り除いて `True` を返す。識別子が未登録であるか，コマンドが実行済みまたはキャンセル済みなら `False` を返す |
| `cancel_from(time_s)` | `time_s` 以降にスケジュールされた実行待ちのコマンドをすべてキャンセルし，それらの識別子を返す |
| `pending()` | 実行待ちの `ScheduledCommand` オブジェクトを実行順に並べたタプルを返す |
| `next_time_s()` | 次の実行待ちのコマンドの時刻を返す。なければ `None` を返す |
| `pop_due(now_s)` | `now_s` 以前に実行時刻を迎えた次のコマンドを取り除いて返す。なければ `None` を返す |

### 規則

- `time_s` が `now_s` より前であるか，有限でないか，数値でない場合，
  あるいは `command` が定義済みのコマンド型のいずれでもない場合，`schedule` は `CommandError` を送出します。
- コマンドをちょうど `now_s` にスケジュールすることもできます。
- コマンド識別子は正の整数で，登録順に1から連番で割り当てられ，再利用されることはありません。
- コマンドは時刻順に実行され，時刻が等しいコマンドは登録順に実行されます。
- 実行待ちでない識別子を渡しても，`cancel` が例外を送出することはありません。
- `cancel_from` は境界を含むため，ちょうど `time_s` にスケジュールされたコマンドもキャンセルされます。
