# spacecraft-operations-challenge-core

[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)

[English](README.md) | **日本語**

Spacecraft Operations Challenge のための Python パッケージです。
参加者は，シミュレーション上の宇宙機を運用する戦略を書きます。
戦略はテレメトリを読み取ってコマンドをスケジュールし，熱・電力・角運動量の制約を守りながら，宇宙機の Δv を目標値まで増やします。

このパッケージは，戦略 API，パラメータで調整できる小さなリファレンスシミュレータ，公開シナリオを含むチャレンジ問題，実行ごとの評価指標，コマンドラインツールを提供します。
宇宙機モデルは，特定の宇宙機やミッションを想定しない簡易モデルです。
配布名は `spacecraft-operations-challenge-core`，インポートするパッケージ名は `spacecraft_ops_challenge` です。

このプロジェクトは開発の初期段階にあり，API は今後も変わる可能性があります。

## 必要なもの

- Python 3.12 以降
- [uv](https://docs.astral.sh/uv/)

実行時に Python 標準ライブラリ以外で依存するのは [packaging](https://packaging.pypa.io/) だけです。

## インストール

別の uv プロジェクトに，Git からこのパッケージを追加します。
`--tag` や `--rev` でバージョンを固定することもできます。

```sh
uv add git+https://github.com/conjikidow/spacecraft-operations-challenge-core
```

## クイックスタート

リポジトリのルートで，チャレンジのシナリオを一覧表示し，API の使用例を実行します。

```sh
uv run spacecraft-ops-challenge scenarios
uv run python examples/timeline_basics.py
```

使用例は小さな例題を題材にして，API の振る舞いを示します。
詳しくは [examples/](examples/README.ja.md) を参照してください。

## 戦略の書き方

`Strategy` を継承し，`initialize` と `update` のどちらか，または両方をオーバーライドします。

```python
from spacecraft_ops_challenge import Commander, MissionBrief, SetHeater, Strategy, Telemetry


class MyStrategy(Strategy):
    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        print(brief.target_delta_v_mps, brief.time_limit_s)
        commander.schedule(600.0, SetHeater(on=True))

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        print(telemetry)
```

チャレンジのシナリオで実行するには，`uv run spacecraft-ops-challenge run my_strategy.py:MyStrategy` とします。
このコマンドは，シミュレーションがどのように終了したかと，その評価指標を出力します。
API の詳細は [戦略の書き方](docs/strategy.ja.md) を参照してください。

## コマンドラインツール

```text
spacecraft-ops-challenge run STRATEGY [--scenario NAME] [--seed N] [--json]
spacecraft-ops-challenge scenarios
```

`STRATEGY` は `FILE.py:CLASS` または `MODULE:CLASS` の形式で指定します。
`CLASS` は `Strategy` のサブクラスで，引数を取らないコンストラクタを持つ必要があります。
ファイルを指定した場合は，そのディレクトリがインポートパスの先頭に追加されるため，戦略を複数のモジュールに分割できます。
モジュールを指定した場合は，カレントディレクトリがインポートパスに追加されます。

`--scenario` でチャレンジのシナリオを選び（デフォルトは `nominal`），
`--seed` でシナリオのシードを上書きし，`--json` で評価指標を JSON として出力します。
`--json` を付けると，戦略が出力した内容はすべて標準エラー出力に送られるため，標準出力は正しい JSON のまま保たれます。
`python -m spacecraft_ops_challenge` は `spacecraft-ops-challenge` と同じ働きをします。

| 終了ステータス | 意味 |
|---|---|
| 0 | シミュレーションが終了した（目標に到達したかどうかは問わない） |
| 1 | シミュレーション中に，戦略が例外を送出したか，タイムラインに不正な要求をした |
| 2 | 使い方の誤り（戦略やシナリオが見つからない場合など） |

## ドキュメント

- [戦略の書き方](docs/strategy.ja.md)：戦略のライフサイクル，`MissionBrief`，`Commander`
- [コマンドとタイムライン](docs/timeline.ja.md)：コマンドの種類とタイムラインの順序規則
- [宇宙機モデル](docs/spacecraft-model.ja.md)：状態，ダイナミクス，テレメトリ，`Modifier`
- [シミュレーション](docs/simulation.ja.md)：問題，シナリオ，イベントの順序，終了条件，実行結果
- [チャレンジ問題](docs/challenge.ja.md)：チャレンジ問題とその公開シナリオ
- [評価](docs/evaluation.ja.md)：実行ごとの評価指標
- [提出アーカイブ](docs/submission.ja.md)：`submission.zip` の作成と展開
- [評価ケース](docs/judge.ja.md)：評価ケース，`Suite`，`ScenarioProvider`
- [参加者のパッケージ](docs/dependencies.ja.md)：提出物が必要とするパッケージの uv による再現

## 開発

プロジェクトと開発用の依存関係をインストールします。

```sh
uv sync
```

テストを実行します。

```sh
uv run pytest
```

[`prek`](https://prek.j178.dev) で Git フックをインストールし，実行します。

```sh
prek install
prek run --all-files
```

wheel とソース配布物を `dist/` にビルドします。

```sh
uv build
```

コミットメッセージは [Conventional Commits](https://www.conventionalcommits.org) に従います。
これはフックの中で Commitizen によって検査されます。

## バージョニング

`update::major`，`update::minor`，`update::patch` のいずれかのラベルを付けたプルリクエストをマージすると，
`bump-version` ワークフローがバージョンを上げるプルリクエストを作成します。
そのプルリクエストをマージすると，`vX.Y.Z` タグと GitHub Release が作成されます。
このワークフローを動かすには，**Settings > Actions > General > Workflow permissions** を開き，
**Allow GitHub Actions to create and approve pull requests** を有効にしておく必要があります。
