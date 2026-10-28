# 結果の表示

[English](views.md) | **日本語**

このページでは，結果文書と依存関係のレポートを [marimo](https://marimo.io) で表示する関数（`spacecraft_autonomy_challenge.judge.views`）について説明します。

## インストール

表示には marimo が必要です。
marimo は，このパッケージの省略可能な `marimo` extra で入ります。

```sh
uv add "spacecraft-autonomy-challenge-core[marimo] @ git+https://github.com/conjikidow/spacecraft-autonomy-challenge-core"
```

marimo がない状態で `spacecraft_autonomy_challenge.judge.views` をインポートすると，
`spacecraft-autonomy-challenge-core[marimo]` を示すメッセージとともに `ImportError` が送出されます。
パッケージのそれ以外の部分は marimo を必要としません。

## 使い方

各関数は `marimo.Html` の要素を返し，それをノートブックのセルの出力として表示します。

```python
from pathlib import Path

import marimo as mo

from spacecraft_autonomy_challenge.judge.reporting import EvaluationResult
from spacecraft_autonomy_challenge.judge.views import dependencies_view, results_view

result = EvaluationResult.from_json(Path("result.json").read_bytes())
mo.vstack([results_view(result), dependencies_view(result.dependencies)])
```

結果文書の作り方は [提出物の評価](evaluating.ja.md) を参照してください。

## 関数

| 関数 | 表示する内容 |
|---|---|
| `results_view(result, *, stats=(), missing_module_hint=DEFAULT_MISSING_MODULE_HINT)` | `EvaluationResult` の `Suite` の得点，集計，評価ケース，得点の定義，得点の内訳，エラー，戦略の出力 |
| `scoring_view(config)` | `ScoringConfig` のパラメータを入れた得点の計算式と，その係数，項，入力の定義 |
| `dependencies_view(report)` | `DependencyReport`，つまり参加者の `pyproject.toml` のパッケージをどう再現したか |
| `score_view(outcomes, scores)` | 各 `CaseScore` の表。得点を `Suite` の得点と同じ尺度で，その係数と項とともに示します。`scores` は `outcomes` と同じ順 |
| `output_view(outcome)` | 1つの `CaseOutcome` の標準出力と標準エラー出力 |
| `text_view(text)` | 等幅フォントのテキスト。空白と改行を保ち，長い行は折り返し，約20行を超えるテキストはその高さの中でスクロールします |

`results_view` は，上から順に次のものを表示します。

1. `Suite` の名前と，参加者の名前（あれば）。
2. 左右に並べた，左の100点満点の `Suite` の得点とその下の `stats` の要素，右の `summary_rows(result.summary)` の集計の簡素な表。
3. 提出物がインポートに失敗したモジュール（`missing_modules` を参照）があれば，それを挙げる警告と `missing_module_hint`。
4. `case_rows(result.outcomes, result.scores)` の評価ケースの表。
   結果の数が `case_ids` より少なければ，表示している評価ケースの数を示す注記。
5. 折りたたまれた，`result.scoring` の `scoring_view`。
6. 折りたたまれた，`score_view` の得点の内訳。
   評価ケースの得点は `Suite` の得点と同じ 0 から 100 の尺度で，その係数と項は 0 から 1 で示します。
7. 折りたたまれた，`problem_outcomes` の各結果の状態と詳細。
   `worker_error` があれば，それも表示します。
8. 折りたたまれた，何かを出力した各評価ケースの標準出力と標準エラー出力。
   どの評価ケースも何も出力しなければ，その旨の注記。

集計と得点は，結果に保存されたとおりに表示し，結果から計算し直すことはありません。
評価ケースの表と得点の内訳では，すべての行が数値（またはないことを示す `-`）の列を右寄せにし，小数点の位置を揃えます。
絞り込まれた結果文書も表示できます。
`None` の `participant`，`case_ids` より少ない結果，空の `stdout`，`stderr`，`detail`，`worker_error` がないことは，それぞれ対応する部分を省いて表示されます。

`DEFAULT_MISSING_MODULE_HINT` は，
`uv add` で追加したパッケージは `submission.zip` に入るプロジェクトの `pyproject.toml` に書かれていなければならず，
自分のモジュールは `submission/` の下に置かなければならない，と伝えます。
別の `missing_module_hint` を渡すと，これを置き換えられます。

`stats` には，別の場所で計算した得点を示す `marimo.stat` など，結果そのものが持たない数値を渡せます。
渡さなければ，左には `Suite` の得点だけが表示されます。

`scoring_view` は，[得点](scoring.ja.md)の計算式を，設定の重みとパラメータを入れて示します。
このため，結果を表示すると，それを採点した設定もわかります。
評価ケースの得点は，表と同じく `Suite` の得点と同じ 0 から 100 の尺度で書きます。
注意が必要な場合（[得点](scoring.ja.md)を参照）は，そのページに任せます。

`dependencies_view` は，提出物に `pyproject.toml` がなければ，評価する環境のパッケージで実行したことを示します。
そうでなければ，その提出物のためだけにインストールしたパッケージ，各パッケージの判定とその理由（[参加者のパッケージ](dependencies.ja.md)を参照），インストーラの各実行の出力を表示します。

これらの関数は，標準出力，標準エラー出力，失敗の詳細，`worker_error`，インストーラの出力を `text_view` で表示するため，長い行は切れずに折り返され，約20行を超えるテキストはその高さの中でスクロールします。
`text_view` はテキストをエスケープするので，テキストが HTML を追加することはありません。
