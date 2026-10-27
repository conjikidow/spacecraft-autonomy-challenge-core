# 提出物の評価

[English](evaluating.md) | **日本語**

このページでは，提出アーカイブ全体を `Suite` で評価する方法（`spacecraft_ops_challenge.judge.judging`）と，
その結果を集計し，JSON の結果文書として記録する方法（`spacecraft_ops_challenge.judge.reporting`）について説明します。

```python
from pathlib import Path

from spacecraft_ops_challenge.judge.judging import check_submission
from spacecraft_ops_challenge.judge.reporting import EvaluationResult

evaluation = check_submission(Path("submission.zip").read_bytes())
result = EvaluationResult.from_evaluation(evaluation, participant="example")
print(result.summary)
Path("result.json").write_text(result.to_json(), encoding="utf-8")
```

## アーカイブの評価

`evaluate_submission(archive, suite, provider)` は，`submission.zip` のバイト列を `suite` のすべての評価ケースで評価します。

1. `provider.check` ですべての評価ケースのシナリオを一度ずつ作成し，壊れた `ScenarioProvider` が提出物の実行前に失敗するようにします。
   この確認は呼び出し側のプロセスで評価ごとに1つずつ行い，その後にプロセスの環境変数を元に戻します。
   パッケージのインストールと評価ケースには，確認の前の環境変数を渡します。
2. アーカイブを一時ディレクトリに展開します（[提出アーカイブ](submission.ja.md)を参照）。
3. アーカイブに `pyproject.toml` があれば，それが挙げるパッケージを，すべての評価ケースで共有する `Overlay` に再現します
   （[参加者のパッケージ](dependencies.ja.md)を参照）。
4. `run_suite` ですべての評価ケースを順に実行します（[評価ケースの実行](runner.ja.md)を参照）。

`Overlay` を含む一時ディレクトリは，その後に削除されます。
`check_submission(archive)` は同じことを公開シナリオで行います。
これは，`public_suite()` と `ScenarioProvider` の `PROVIDER` を渡した `evaluate_submission` です（[評価ケース](judge.ja.md)を参照）。

どちらも次のキーワード引数を受け取ります。

| 引数 | 意味 |
|---|---|
| `timeout_s` | 1つの評価ケースの実時間の上限（デフォルトは `DEFAULT_CASE_TIMEOUT_S`，300 秒） |
| `on_status` | パッケージを準備する前と評価ケースを実行する前に，短い進捗メッセージとともに呼び出される |
| `on_case_done` | 各 `CaseOutcome` が得られるたびに，それとともに呼び出される |

壊れた `ScenarioProvider` に対しては `CaseError`，不正なアーカイブに対しては `SubmissionError`，
再現できないパッケージに対しては `DependencyError` が送出され，これらの場合はどの評価ケースも実行されません。
失敗した評価ケースは例外を送出せず，その状態とともに結果に含まれます。

どちらも，次のフィールドを持つ `SubmissionEvaluation` を返します。

| フィールド | 意味 |
|---|---|
| `suite` | 評価した `Suite` |
| `outcomes` | すべての評価ケースの `CaseOutcome`（`Suite` の順） |
| `submission_sha256` | アーカイブのバイト列の SHA-256（16進文字列） |
| `skipped_entries` | 展開しなかったアーカイブのエントリ。`pyproject.toml` を除く，`submission/` の外にあるもの |
| `dependencies` | 参加者のパッケージの `DependencyReport` |
| `started_at`，`finished_at` | 秒単位の ISO 8601 形式の UTC 時刻 |

## 集計統計

`summarize(outcomes)` は，1つの `Suite` の結果を集計した `SuiteSummary` を返します。

| フィールド | 意味 |
|---|---|
| `cases` | 結果の数 |
| `completed` | 実行の評価指標が得られた評価ケースの数 |
| `not_completed` | 読み込めなかった，クラッシュした，または時間切れになった評価ケースの数 |
| `safe` | 安全だった完了した実行の数 |
| `completion_declared` | 完了を宣言した完了した実行の数 |
| `safe_and_completion_declared` | 安全で，かつ完了を宣言した完了した実行の数 |
| `strategy_failures` | `STRATEGY_ERROR` または `INVALID_COMMAND` で終了した完了した実行の数 |
| `termination_reasons` | 終了理由ごとの完了した実行の数 |
| `statuses` | `CaseStatus` ごとの評価ケースの数 |
| `mean_abs_delta_v_error_mps`，`median_abs_delta_v_error_mps` | 完了した実行での Δv の誤差の絶対値の平均と中央値。完了した実行がなければ `None` |
| `mean_abs_delta_v_error_safe_declared_mps`，`median_abs_delta_v_error_safe_declared_mps` | 安全で，かつ完了を宣言した実行での同じ値。そのような実行がなければ `None` |

`to_dict()` は JSON に変換できるデータを返し，`SuiteSummary.from_dict` はその逆変換です。
`from_dict` は，`SuiteSummary` を表さないデータに対して `ValueError` を送出します。

表に表示するために，`summary_rows(summary)` と `case_rows(outcomes)` は人が読める文字列の行を返します。
`case_rows` は評価ケースごとに1行で，状態，終了理由，主な評価指標，実時間，参加者のプロセスの CPU 時間を持ち，
得られない値は `-` と表示します。
`problem_outcomes(outcomes)` は，詳しく見る価値のある結果，つまり完了しなかった評価ケースと，戦略の失敗で終了した完了した実行を返します。
`missing_modules(outcomes)` は，提出物がインポートに失敗したモジュールの名前を整列して返します。

得点，成否の基準，合格の閾値はどこにも適用されません。
集計と行が示すのは，数と評価指標だけです。

## 結果文書

`EvaluationResult` は1回の評価の記録で，評価を再実行せずに結果を集計できるだけの内容を持ちます。
`EvaluationResult.from_evaluation(evaluation, participant=None)` は，`SubmissionEvaluation` からこれを作成します。
`summary` はすべての結果に対する `summarize` の値，`core_version` はこのパッケージのバージョンです。
`participant` は，アーカイブを提出した人の名前で，省略できます。

この記録は，評価ケースを ID だけで，`Suite` を `fingerprint` だけで識別し，評価ケースの `payload` は決して含みません。
保存して後で読み込むことも，他の人に渡すこともできます。

| メソッド | 意味 |
|---|---|
| `to_dict(include_worker_errors=False)` | JSON に変換できる辞書としての結果文書 |
| `EvaluationResult.from_dict(data)` | `to_dict` の逆変換 |
| `to_json(include_worker_errors=False)` | 2つの空白で字下げし，改行で終わる JSON テキストとしての結果文書 |
| `EvaluationResult.from_json(text)` | `to_json` の逆変換。任意の JSON の書式の `str` または `bytes` を受け取る |

結果文書は，次のキーを持つ JSON オブジェクトです。

| キー | 意味 |
|---|---|
| `format` | 常に `RESULT_FORMAT`，つまり `"spacecraft-operations-challenge/result"` |
| `format_version` | 常に `RESULT_FORMAT_VERSION`，現在は `1` |
| `participant` | 参加者の名前，または `null` |
| `submission` | アーカイブの `{"sha256": ..., "skipped_entries": [...]}` |
| `dependencies` | `DependencyReport.to_dict()`（[参加者のパッケージ](dependencies.ja.md)を参照） |
| `suite` | `{"name": ..., "fingerprint": ..., "case_ids": [...]}`。`case_ids` は `Suite` のすべての評価ケースの ID を順に並べたもの |
| `core_version` | 評価を実行したこのパッケージのバージョン |
| `started_at`，`finished_at` | ISO 8601 形式の UTC 時刻 |
| `summary` | `SuiteSummary.to_dict()` |
| `cases` | 各結果の `CaseOutcome.to_dict()`（[評価ケースの実行](runner.ja.md)を参照）。`include_worker_errors` が真でなければ `worker_error` を除きます |

結果文書は，例えば別の読み手のために詳細を省くなど，読み込む前に絞り込まれていることがあります。
`worker_error` のほか，`dependencies` のインストーラのコマンドと出力には，評価するマシンのパスが現れます。
そのため `from_dict` は，`null` の `participant`，`case_ids` より少ない `cases`，
空文字列の `stdout`，`stderr`，`detail`，`worker_error` のない評価ケースを受け付けます。
ただし，`cases` は `Suite` の異なる評価ケースで，`case_ids` の順でなければならず，
評価指標は `COMPLETED` の評価ケースにだけあり，集計の数は負であってはなりません。
保存された `summary` は，`cases` から計算し直されることなく，そのまま読み込まれます。

`from_dict` と `from_json` は，`format` や `format_version` が異なる文書，JSON ではないテキスト，有限でない数値，
文書，その `summary` と `cases`，報告の関数が読む評価ケースの評価指標でのキーの欠落や型の誤った値に対して，
`ValueError` のサブクラスである `ResultFormatError` を送出します。
依存関係のレポートは，構造だけを検査します。
形式が定義していないキーは無視されます。

結果文書を読み込んで再び `to_dict()` を呼び出すと，同じ文書が得られます。
評価ケースに `worker_error` がある文書では，`include_worker_errors=True` を指定します。
依存関係の判定の制約と保護するパッケージは結果文書に含まれないため（[参加者のパッケージ](dependencies.ja.md)を参照），
読み込んだ結果が元の結果と異なりうるのはその点だけです。
