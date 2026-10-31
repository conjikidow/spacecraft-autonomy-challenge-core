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
uv run python examples/planning_internal_model.py
uv run python examples/planning_external_file.py
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

## `planning_internal_model.py` と `planning_external_file.py`

この2つの戦略は，[Unified Planning](https://unified-planning.readthedocs.io/) を通じて，プランニングエンジンから計画を得ます。
どちらも同じ抽象的なモデルを解きます。このモデルは噴射の区切りを数えるだけで，宇宙機については何も知りません。
`planning_internal_model.py` は，モデルを Python で構築します。
`planning_external_file.py` は，`Path(__file__)` から作ったパスを使って，`toy_burn.anml` からモデルを読み込みます。
文字列からモデルを読み込むには `ANMLReader().parse_problem_string(text)` を使い，
PDDL ファイルは `unified_planning.io` の `PDDLReader` で読み込めます。

どちらの戦略も，複数のエンジン名を `OneshotPlanner(names=...)` に渡します。
これによりエンジンが別々のプロセスで並列に実行されます。
問題に品質指標（quality metric）を追加しているのは，そうすると最初に得られた計画が返るためです。
指標がないと，すべてのエンジンの終了を待ちます。
`up-tamer` には arm64 向けのパッケージがなく，`up-aries` はより多くのプラットフォームに対応しているため，インストールされているエンジンだけを使います。

リポジトリの開発環境には，これらのパッケージがすでに入っています。
提出物で使うには，プロジェクトに追加します。

```sh
uv add unified-planning up-aries "up-tamer; platform_machine == 'x86_64'"
```

戦略のファイルは，それぞれ単独で完結しています。
試すには，ファイルを `submission/strategy.py` にコピーし（`planning_external_file.py` の場合は隣に `toy_burn.anml` も置きます），
クラス名を `MyStrategy` に変更します。

`unified-planning` のバージョン 1.3.0 では，次の点に注意してください。

- 指定したエンジンのどれかが問題を扱えない場合や，インストールされていない場合は，他のエンジンで解ける問題でも呼び出し全体が失敗します。
  そのため，問題に合うエンジンだけを指定してください。
- `OneshotPlanner(names=...)` では，指定するエンジンの数によらず，`planner.solve` の `timeout` は効きません。
  どのエンジンも終わらないと，戦略はケースの制限時間まで待ち続けるので，モデルは小さく保ってください。
- 品質指標があっても，最初に返る計画が最良とは限りません。
- エンジンが問題を解けるか判断できないという警告は，警告にすぎません。そのエンジンが問題を解くこともあります。

## `toy_problem.py`

`toy_scenario()` は例題のシナリオを構築し，`run_and_report(strategy)` はそのシナリオで戦略を実行して結果を出力します。
`timeline_basics.py` と `telemetry_and_replanning.py` がインポートするのは，
トップレベルの `spacecraft_autonomy_challenge` パッケージだけです。
一方 `toy_problem.py` は，シナリオの構築と実行のためにシミュレーション関連のモジュールも使います。
