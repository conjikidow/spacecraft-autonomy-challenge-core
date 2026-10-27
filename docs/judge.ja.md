# 評価ケース

[English](judge.md) | **日本語**

このページでは，評価ケース，`Suite`，`ScenarioProvider`（`spacecraft_autonomy_challenge.judge.cases`）と，
公開シナリオ用の `ScenarioProvider`（`spacecraft_autonomy_challenge.judge.public_scenarios`）について説明します。
これらは，提出物を評価するシナリオを定義します。
提出物をそれらで実行する方法は[評価ケースの実行](runner.ja.md)を，
アーカイブ全体を `Suite` で評価する方法は[提出物の評価](evaluating.ja.md)を参照してください。

```python
from spacecraft_autonomy_challenge.judge.cases import EvaluationCase, ScenarioProvider, Suite

suite = Suite("example", (EvaluationCase.of("case-001", {"seed": 1}), EvaluationCase.of("case-002", {"seed": 2})))
provider = ScenarioProvider("my_cases.provider:build_scenario", paths=("path/to/directory/of/my_cases",))
provider.check(suite.cases)
scenario = provider.build(suite.cases[0])
```

提出物を評価する側は，独自の評価ケースと `ScenarioProvider` を定義できます。
不正な評価ケース，`Suite`，`ScenarioProvider` に対しては，`ValueError` のサブクラスである `CaseError` が送出されます。

## 評価ケース

`EvaluationCase` は，ID と，JSON データの辞書である `payload` の組です。
`payload` の意味を解釈するのは `ScenarioProvider` だけで，それ以外にとって `payload` は中身を問わないデータです。

- `EvaluationCase.of(case_id, payload)` は，JSON に変換できる辞書から評価ケースを作成します。
- `EvaluationCase(case_id, payload_json)` は，JSON 文字列から評価ケースを作成します。
- `payload` は内容の新しいコピーを返します。これを変更しても評価ケースは変わりません。
- `to_dict()` は `{"id": ..., "payload": ...}` を返し，`EvaluationCase.from_dict` はその逆変換です。

ID は空でない文字列でなければなりません。
`payload`は有限の値からなる JSON データの辞書でなければならず，`NaN` と無限大は拒否されます。

`payload`は，キーを整列し空白を除いた正規形の JSON として `payload_json` に格納されます。
そのため，評価ケースは不変かつハッシュ可能で，ID と`payload`が等しい2つの評価ケースは，キーの順序によらず等しくなります。

## `Suite`

`Suite` は，名前の付いた，順序のある評価ケースの集まりです。
評価ケースの ID は重複してはなりません。

`fingerprint` は，評価ケースの ID と`payload`を正規形の JSON にしたものの SHA-256 を，16進数の文字列で表したものです。
評価ケースの内容を明かさずに，順序を含めて評価ケースを正確に識別できます。
`Suite` の名前は `fingerprint` に含まれません。

## `ScenarioProvider`

シナリオを作成する関数は，`payload` を受け取って `Scenario`（[シミュレーション](simulation.ja.md)を参照）を返す，モジュールのトップレベルで定義された関数です。
`ScenarioProvider` は，この関数を `module:function` の形式で指定します。
`paths` は，インストールされていないコードのために，関数を読み込むときにインポートパスへ追加するディレクトリで，絶対パスとして格納されます。

| 名前 | 意味 |
|---|---|
| `ScenarioProvider.from_callable(function)` | モジュールのトップレベルで定義された関数の `ScenarioProvider`。その関数のトップレベルパッケージがあるディレクトリを `paths` とします |
| `load()` | `paths` を現在のプロセスのインポートパスの末尾に追加して，関数をインポートします |
| `build(case)` | `case` のシナリオ。関数が `Scenario` を返さない場合は `CaseError` |
| `check(cases)` | すべての評価ケースのシナリオを1回ずつ作成し，壊れた `ScenarioProvider` を早い段階で検出します |
| `to_dict()` | `{"target": ..., "paths": [...]}`。`ScenarioProvider.from_dict` はその逆変換で，不正なデータには `CaseError` を送出します |

`load` は，モジュールや関数が見つからない場合と，指定先が呼び出し可能でない場合に `CaseError` を送出します。
`paths` を持つ `ScenarioProvider` では，インストール済みやインポート済みの同名モジュールなど，
モジュールが `paths` 以外の場所から読み込まれた場合にも `CaseError` を送出します。
`check` は，関数が送出したそれ以外の例外も，失敗した評価ケースを示す `CaseError` に変換します。
`module:function` の形式でない指定先に対しては `CaseError` が送出されます。
`from_callable` も，`__main__` で定義された関数など，
インポート可能なモジュールのトップレベルで定義されていない関数に対して `CaseError` を送出します。

## 公開シナリオ

`spacecraft_autonomy_challenge.judge.public_scenarios` は，チャレンジの公開シナリオ（[チャレンジ問題](challenge.ja.md)を参照）で評価するためのもので，独自の評価ケースなしで評価を試せます。

```python
from spacecraft_autonomy_challenge.judge.public_scenarios import PROVIDER, public_suite

suite = public_suite()
scenarios = [PROVIDER.build(case) for case in suite.cases]
```

- `PROVIDER` は，`spacecraft_autonomy_challenge.judge.public_scenarios:build_scenario` を指定する `ScenarioProvider` です。
- `payload`は `{"scenario": name}` または `{"scenario": name, "seed": seed}` です。
  `name` は `scenario_names()` のいずれかで，`seed` が `None` でなければシナリオのシードを置き換えます。
- `public_suite()` は，公開シナリオごとに1つの評価ケースを持つ 名前が `public` の `Suite` を返します。評価ケースの ID はシナリオ名です。
