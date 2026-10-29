# 提出アーカイブ

[English](submission.md) | **日本語**

このページでは，提出アーカイブ（`spacecraft_autonomy_challenge.judge.submission`）について説明します。
提出アーカイブ `submission.zip` は，戦略とそれが使うファイルをまとめたものです。

```python
from pathlib import Path

from spacecraft_autonomy_challenge.judge.submission import build_submission, extract_submission

Path("submission.zip").write_bytes(build_submission("."))
submission = extract_submission("submission.zip", Path("extracted"))
print(submission.strategy_file, submission.pyproject is not None)
```

コマンドラインでは，`autonomy-challenge pack` でプロジェクトディレクトリから `submission.zip` を作成できます（[README](../README.ja.md#コマンドラインツール)を参照）。

## アーカイブの構成

アーカイブの構成は，作成元のプロジェクトのルートディレクトリと同じです。

| エントリ | 意味 |
|---|---|
| `submission/strategy.py` | エントリポイント。戦略クラス `MyStrategy` を定義します |
| `submission/...` | 追加のモジュール，データ，モデルファイルなど，戦略が使う任意のファイル |
| `pyproject.toml` | 省略可能。提出物が必要とするパッケージを記載した，プロジェクトの `pyproject.toml`（[参加者のパッケージ](dependencies.ja.md)を参照） |

定数 `SUBMISSION_DIRNAME`，`STRATEGY_PATH`，`STRATEGY_CLASS`，`PYPROJECT_PATH` は，これらの名前を表します。

## アーカイブの作成

`build_submission(project_dir)` は，プロジェクトディレクトリから作成した `submission.zip` をバイト列として返します。

- `project_dir/submission/` 以下のすべてのファイルを `submission/<相対パス>` として追加します。
- `__pycache__` ディレクトリと，`.pyc` および `.pyo` ファイルは含めません。
- `project_dir/pyproject.toml` が通常のファイルであれば，`pyproject.toml` として追加します。
- プロジェクトディレクトリにあるそれ以外のものと，空のディレクトリは追加しません。

プロジェクトが次のいずれかに当てはまる場合は，`SubmissionError` が送出されます。

- `submission/strategy.py` がない。
- `submission/` 自体，その中のいずれか，または `pyproject.toml` がシンボリックリンクである。シンボリックリンクはたどらずに拒否します。
- `submission/` の中に，名前付きパイプなど，通常のファイルでないものがある。
- `submission/` の中に，パスにバックスラッシュを含むファイルがある。
- ファイルの合計サイズが `max_total_bytes`（デフォルトは `DEFAULT_MAX_TOTAL_BYTES` の 512 MiB）を超える。

読み取れないファイルがある場合は，`OSError` が送出されます。

作成されるアーカイブは決定的です。
エントリは名前順に並べられ，`ZIP_DEFLATED` で圧縮され，固定のタイムスタンプ（1980-01-01 00:00:00）と固定のパーミッションで格納されます。
そのため，ファイルのタイムスタンプやパーミッションによらず，
ファイルの内容が同じであれば，アーカイブのバイト列も SHA-256 ハッシュも同じになります。
`build_submission` が返すアーカイブは，どれも `extract_submission` で展開できます。

## アーカイブの展開

`extract_submission(archive, destination)` は，アーカイブを検証し，その `submission/` ディレクトリを `destination` に展開します。
`archive` はパスまたはバイナリのファイルオブジェクトで，`destination` は空のディレクトリか，まだ存在しないパスでなければなりません。
最初に `destination` と存在しない親ディレクトリを作成し，`destination` が空でなければ `ValueError` が送出されます。
ファイルを展開する前に，すべてのエントリを検証します。

次のいずれかに当てはまる場合は，ファイルを何も展開せずに `SubmissionError` が送出されます。

- 絶対パス，ドライブ文字，`..`，バックスラッシュを含むエントリがある。
- シンボリックリンクなどの特殊ファイルのエントリがある（`submission/` の外にあるものも含む）。
- 暗号化されたエントリがある。
- 展開するエントリまたはルートの `pyproject.toml` と同じ名前のエントリが複数ある，またはその名前がディレクトリとしても使われている。
- アーカイブに `submission/strategy.py` がない。
- 有効な ZIP アーカイブでない。
- 展開後のファイルの合計サイズが `max_total_bytes`（デフォルトは `DEFAULT_MAX_TOTAL_BYTES`）を超える。

チェックサムの不一致など，展開の途中でエントリの破損がわかった場合や，エントリが Python の読めない圧縮方式を使っている場合は，
`SubmissionError` が送出され，それまでに書き込んだファイルは削除されます。

`submission/` の外にあるエントリと，アーカイブのルートに直接置かれたファイルは展開しません。
ただし，アーカイブのルートにある `pyproject.toml` は，展開せずに内容を読み込みます。
サイズの上限には，展開するすべてのファイルと `pyproject.toml` が含まれます。

戻り値の `Submission` は，次のフィールドとプロパティを持ちます。

| 名前 | 意味 |
|---|---|
| `root` | 絶対パスに解決した `destination`。`submission/` を含みます |
| `skipped_entries` | 展開しなかったエントリの名前 |
| `pyproject` | アーカイブのルートにある `pyproject.toml` の内容。なければ `None` |
| `directory` | 展開した `submission/` ディレクトリ |
| `strategy_file` | 展開した `submission/strategy.py` |
