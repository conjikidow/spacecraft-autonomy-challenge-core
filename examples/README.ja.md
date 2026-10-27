# 使用例

[English](README.md) | **日本語**

これらの使用例は，戦略 API がどのように振る舞うかを示します。
使用例は，`toy_problem.py` で定義した小さな例題を題材にしています。
この例題は，チャレンジ問題とは意図的に異なる設定にしてあり，制約も緩くしてあります。
これらは，チャレンジ用の戦略ではありません。

リポジトリのルートで実行します。

```sh
uv run python examples/timeline_basics.py
uv run python examples/telemetry_and_replanning.py
```

各スクリプトは，実行されたコマンド，シミュレーションがどのように終了したか，真の Δv を出力します。

## `timeline_basics.py`

`TimelineBasics` は，`initialize` でコマンドのタイムライン全体を登録し，`update` はオーバーライドしません。
シミュレーションは，それ以上コールバックを呼ばずに，すべてのコマンドをそれぞれスケジュールされた時刻に実行します。
また，もう一方のスラスタを選ぶと最初のスラスタが停止することと，同じ時刻のコマンドは登録順に実行されることも示します。

## `telemetry_and_replanning.py`

`TelemetryAndReplanning` は，`execute` でスラスタをすぐに始動し，はるか先の時刻に仮の停止コマンドをスケジュールします。
`update` のたびに，受け取ったテレメトリを出力します。
60秒の時点で，仮の停止コマンドを識別子で指定してキャンセルし，
さらに `cancel_from` で現在時刻以降のコマンドをすべてキャンセルしてから，
`DeclareCompletion` で終わる代替計画を登録します。

## `toy_problem.py`

`toy_scenario()` は例題のシナリオを構築し，`run_and_report(strategy)` はそのシナリオで戦略を実行して結果を出力します。
戦略のファイルがインポートするのは，トップレベルの `spacecraft_autonomy_challenge` パッケージだけです。
一方 `toy_problem.py` は，シナリオの構築と実行のためにシミュレーション関連のモジュールも使います。
