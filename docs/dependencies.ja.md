# 参加者のパッケージ

[English](dependencies.md) | **日本語**

このページでは，提出物が必要とするパッケージを再現する方法（`spacecraft_autonomy_challenge.judge.dependencies`）について説明します。
提出物は，必要なパッケージをアーカイブの任意の `pyproject.toml` に記載します（[提出アーカイブ](submission.ja.md)を参照）。

```python
from pathlib import Path

from spacecraft_autonomy_challenge.judge.dependencies import resolve_dependencies
from spacecraft_autonomy_challenge.judge.submission import extract_submission

submission = extract_submission("submission.zip", Path("work/extracted"))
report, overlay = resolve_dependencies(submission.pyproject, Path("work/overlay"))
env = None if overlay is None else overlay.environment()
```

提出物を評価する環境そのものは変更しません。
各要件をその環境と照らし合わせ，環境に足りないものだけを別のディレクトリ `Overlay` にインストールします。
インストールには，実行時に `PATH` 上に [uv](https://docs.astral.sh/uv/) が必要です。
インストールするものがなければ，uv は不要です。

`pyproject.toml` を読めない場合，再現できない要件がある場合，インストールに失敗した場合は，
`ValueError` のサブクラスである `DependencyError` が送出されます。

## 要件

要件は，参加者の `pyproject.toml` の `[project] dependencies` の各項目で，`parse_requirements` が読み取ります。
`pyproject.toml` がなければ，提出物は評価する環境のパッケージだけで実行されます。

各要件には，評価する環境に対して `Decision` が1つ決まります。

| `Decision` | 条件 |
|---|---|
| `NOT_APPLICABLE` | 環境マーカーが，評価するインタプリタに対して偽である |
| `JUDGE_CONTROLLED` | `spacecraft-autonomy-challenge-core` である |
| `SATISFIED` | インストール済みのバージョンと extra が要件を満たす，または同じ URL からインストール済みである |
| `INSTALL` | 未インストールである，バージョンや extra が満たされていない，または別の URL を指定している |
| `UNSUPPORTED` | 要件自体，その `[tool.uv.sources]` の項目，または指定した extra の依存関係を再現できない。または環境マーカーを評価できない |

- 評価する環境は常に自身のコアパッケージを使い，理由には，参加者が指定したコアがそれと一致するかが示されます。
  その指定の `[marimo]` などの extra も再現しません。
- `file://` のパッケージは，評価する環境に同じ名前のパッケージがローカルのファイルからインストールされていれば，パスによらず満たされているとみなします。
  そうでなければ，ファイルが存在すればインストールし，存在しなければ `UNSUPPORTED` です。
- `helper @ ../helper` のような相対パスによる直接参照は，参加者のプロジェクトではなく評価する側で解決されてしまうため，
  `UNSUPPORTED` です。
- 解析できない URL による直接参照は，コアパッケージを除き `UNSUPPORTED` です。
- URL の要件は，サブディレクトリも同じ場合にだけ一致します。
- インストール済みのパッケージに，指定した extra の依存関係が足りない場合は，その依存関係だけをインストールします。
  extra の依存関係も，ほかの要件と同じように判定します。

`decide` は1つの要件を判定し，`plan_dependencies` はすべての要件を順に判定して `DependencyPlan` を返します。
`UNSUPPORTED` の要件が1つでもあれば，`resolve_dependencies` は，その要件と理由を示すメッセージとともに停止します。

## `[tool.uv.sources]` の取得元

`uv add git+https://example.com/lib.git --tag v1` のように，インデックス以外の取得元からパッケージを追加すると，
`uv add` は `[project] dependencies` にパッケージ名だけを記録し，
取得元を `[tool.uv.sources]` に記録します
（uv のドキュメントの [Dependency sources](https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-sources) を参照）。
取得元を使わないと，名前だけの要件が，デフォルトのインデックスにある同名の無関係なパッケージに解決されるおそれがあります。
`parse_sources` は，正規化したパッケージ名をキーとして各項目を読み取り，同じ名前の要件はその項目を使います。

| 項目 | 結果 |
|---|---|
| `{ git = URL }`。`tag`，`branch`，`rev` のいずれか1つまでと，任意の `subdirectory` を指定できます | `name[extras] @ git+URL@REVISION#subdirectory=SUBDIRECTORY ; marker` |
| `{ url = URL }`。任意の `subdirectory` を指定できます | `name[extras] @ URL#subdirectory=SUBDIRECTORY ; marker` |
| `{ path = ... }` または `{ workspace = ... }` | `UNSUPPORTED`。そのコードを `submission/` 以下に置くか，パッケージを公開してください |
| `{ index = ... }` | `UNSUPPORTED`。指定したインデックスは使われず，デフォルトのインデックスでは別のパッケージになるおそれがあります |
| 取得元のリスト，またはそれ以外の項目やキー | `UNSUPPORTED` |

- 書き換えた要件は，元の要件の extra と環境マーカーを保ちます。
  URL の要件にはバージョン指定を含められないため，バージョン指定は除かれます。
- `git` の URL は `git+` で始まっていてもかまいません。
  URL に空白，`;`，`#` を含む項目と，リビジョンやサブディレクトリにさらに `@`，`&`，`?` を含む項目は，
  別の要件に書き換えずに `UNSUPPORTED` とします。
- `marker` を持つ項目は，そのマーカーが評価するインタプリタに対して真の場合にだけ適用し，偽の場合は要件を書かれたとおりに判定します。
- 書き換えた要件の判定には書き換えた要件が記録され，その理由には元の要件が示されます。
- `spacecraft-autonomy-challenge-core` の要件は，取得元によらず `JUDGE_CONTROLLED` のままです。
  環境マーカーが偽の要件も `NOT_APPLICABLE` のままです。
- `[project] dependencies` にないパッケージの項目は無視します。
- `foo_bar` と `Foo-Bar` のように，正規化すると同じパッケージになる名前の項目が2つあると，`DependencyError` を送出します。

## `Overlay` へのインストール

`INSTALL` の要件は，提出物ごとに1回，`uv pip install --target` で新しいディレクトリにインストールします。
これを行うのは `install_overlay` で，`resolve_dependencies` はインストールするものがある場合にだけこれを呼び出します。
uv は `--no-config` を付けて実行するため，ディレクトリの周りの設定ファイルはインストールに影響しません。
uv は `env` で渡した環境変数（省略すると現在のプロセスの環境変数）の `PATH` で探し，その環境変数で実行します。
uv は，要件のファイルを置いた，インストール先の隣の一時ディレクトリで実行し，そのディレクトリは後で削除します。

- 最初の試行では，評価する環境がインデックスからインストールしたパッケージのバージョン（`base_constraints`）に制約し，
  `Overlay` が別のバージョンでそれらを隠さないようにします。
- その試行が理由を問わず失敗した場合は，この制約なしでインストールをやり直します。
- どちらの試行も，評価する環境がすでに満たしているバージョン要件（指定した extra の依存関係を含む）にも制約します。
- `timeout_s`（デフォルトは `DEFAULT_INSTALL_TIMEOUT_S`，900 秒）より長くかかった試行は失敗とします。

インストール後，`Overlay` がコアパッケージのモジュール（`PROTECTED_MODULES`）を含む場合や，
参加者の `pyproject.toml` が URL で指定し，
評価する環境がすでにその URL からインストールしているパッケージを置き換える場合は，`DependencyError` が送出されます。

戻り値の `Overlay` は，ディレクトリとインストーラの実行記録を持ちます。
`Overlay.environment(base)` は，`base`（デフォルトは現在のプロセスの環境変数）の `PYTHONPATH` の先頭にディレクトリを追加したものを返します。
これは参加者のコードを実行するプロセスのためのもので，そのプロセスでは `Overlay` のパッケージが評価する環境のパッケージより優先されます。

## レポート

`resolve_dependencies(pyproject, target)` は，`DependencyReport` と，`Overlay`（何もインストールしなかった場合は `None`）を返します。
レポートは，`DependencyPlan`（`pyproject.toml` がなければ `None`）と，すべての `InstallAttempt` を持ちます。

レポート，`DependencyPlan`，判定（`RequirementDecision`），`InstallAttempt` の `to_dict()` は JSON に変換できるデータを返し，
`from_dict` はその逆変換です。
判定の制約と保護するパッケージは，インストールにだけ使うもので，これには含まれません。
