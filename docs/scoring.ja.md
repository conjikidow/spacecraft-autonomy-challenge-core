# 得点

[English](scoring.md) | **日本語**

このページでは，評価した評価ケースと `Suite` の得点の計算方法（`spacecraft_ops_challenge.judge.scoring`）について説明します。
得点は，評価ケースの状態と実行の評価指標（[評価](evaluation.ja.md)を参照），参加者のプロセスの CPU 時間（[評価ケースの実行](runner.ja.md)を参照），得点の設定だけから決まります。

```python
from pathlib import Path

from spacecraft_ops_challenge.judge.judging import check_submission
from spacecraft_ops_challenge.judge.scoring import ScoringConfig, score_case, suite_score

config = ScoringConfig.default()
evaluation = check_submission(Path("submission.zip").read_bytes(), scoring=config)
scores = [score_case(outcome, config) for outcome in evaluation.outcomes]
print(suite_score(scores))
```

## 評価ケースの得点

1つの評価ケースの得点 $s$ は，0から1までの数です。

$$
s = g \cdot a \cdot d \cdot
\left( w_\mathrm{base} + w_\mathrm{time} \, t + w_\mathrm{battery} \, b + w_\mathrm{cpu} \, c \right)
$$

$g$，$a$，$d$ の3つの係数は，得点全体に掛かります。
重み $w$ は設定から与えられ，負でなく，合計は1です。
そのため，基本項と $t$，$b$，$c$ の各項の重み付き和は1以下です。
どの係数と項も0から1までの値をとります。

| 記号 | `CaseScore` のフィールド | 定義 |
|---|---|---|
| $g$ | `gate` | 評価ケースの状態が `COMPLETED` で，評価指標 `safe` が真で，終了理由が `STRATEGY_ERROR` でも `INVALID_COMMAND` でもなければ1，それ以外は0 |
| $a$ | `accuracy` | $\max\left(0, 1 - \lvert e \rvert / e_\mathrm{tol}\right)$。$e$ は Δv の誤差，$e_\mathrm{tol} = f_\mathrm{tol} \cdot \Delta v_\mathrm{target}$ は許容誤差 |
| $d$ | `declaration` | 完了を宣言した実行なら1，そうでなければ未宣言の係数 $f_\mathrm{undeclared}$ |
| $t$ | `completion_time` | 完了を宣言した実行なら $1 - t_\mathrm{declared} / T$，そうでなければ0 |
| $b$ | `battery_margin` | $\left(E_\mathrm{min} - E_\mathrm{limit}\right) / \left(C_\mathrm{nominal} - E_\mathrm{limit}\right)$ を0から1の範囲に切り詰めた値 |
| $c$ | `cpu_time` | $\min\left(1, B / \tau\right)$。$\tau$ は参加者のプロセスの CPU 時間，$B = B_\mathrm{startup} + B_\mathrm{cycle} \cdot T / \Delta t$ は CPU 時間の予算 |

各量は，実行の評価指標と結果から取ります。

| 記号 | 出典 |
|---|---|
| $e$ | `delta_v_error_mps` |
| $\Delta v_\mathrm{target}$ | `target_delta_v_mps` |
| $t_\mathrm{declared}$ | `completion_declared_time_s` |
| $T$ | `time_limit_s` |
| $\Delta t$ | `decision_period_s` |
| $E_\mathrm{min}$ | `min_battery_energy_wh` |
| $E_\mathrm{limit}$ | `min_battery_energy_limit_wh` |
| $C_\mathrm{nominal}$ | `nominal_battery_capacity_wh` |
| $\tau$ | `CaseOutcome` の `participant_cpu_s` |

バッテリの余裕は，`MissionBrief` が戦略に与える公称容量と安全制約を基準に測ります。

次の場合には注意が必要です。

- 評価指標のない評価ケース（状態が `LOAD_ERROR`，`CRASHED`，`TIMEOUT`）の得点は0で，すべての係数と項も0です。
- 早く完了を宣言するだけでは得点になりません。Δv の誤差が $e_\mathrm{tol}$ 以上なら，$a$ と得点は0です。
- $\tau$ が `None` なら $c = 0$ です。CPU 時間を測れなかった完了した実行もこれに含まれます。$\tau$ が0なら $c = 1$ です。
- 参加者のプロセスが起動したプロセスが $\tau$ に含まれるのは，[評価ケースの実行](runner.ja.md)で説明する場合だけです。
  参加者のプロセスが終了したときにまだ実行中のプロセスは含まれません。
- 目標 Δv が0なら，$a$ は誤差がちょうど0のとき1，それ以外は0です。
- $C_\mathrm{nominal}$ が $E_\mathrm{limit}$ より大きくなければ，$b = 0$ です。

完了した実行では，得点が0である理由を説明できるように，$g$ が0でもすべての係数と項を計算します。

## `Suite` の得点

`Suite` の得点は，0から100までの数です。

$$
S = \frac{100}{N} \sum_{i=1}^{N} s_i
$$

$N$ は `Suite` の評価ケースの数，$s_i$ は評価ケース $i$ の得点です。
評価指標のない評価ケースは $s_i = 0$ として数えます。
合格の閾値は適用されません。

## 設定

計算式の値はコードに固定されていません。
`ScoringConfig` は，TOML から読み込んだ値を4つのセクションに分けて持ちます。
このパッケージは，次の設定を `spacecraft_ops_challenge/judge/scoring.toml` として含みます。

```toml
version = 1

[accuracy]
tolerance_fraction = 0.1

[declaration]
undeclared_factor = 0.5

[weights]
base = 0.70
completion_time = 0.15
battery_margin = 0.10
cpu_time = 0.05

[cpu_time]
startup_allowance_s = 5.0
per_decision_cycle_s = 0.1
```

| キー | 記号 | 意味 | 同梱の値 |
|---|---|---|---|
| `version` | | 設定の形式のバージョン。1でなければならない | `1` |
| `accuracy.tolerance_fraction` | $f_\mathrm{tol}$ | $a$ が0になる Δv の誤差の絶対値の，目標 Δv に対する比 | `0.1` |
| `declaration.undeclared_factor` | $f_\mathrm{undeclared}$ | 完了を宣言しなかった実行の $d$ | `0.5` |
| `weights.base` | $w_\mathrm{base}$ | 基本項の重み | `0.70` |
| `weights.completion_time` | $w_\mathrm{time}$ | 完了時刻の項の重み | `0.15` |
| `weights.battery_margin` | $w_\mathrm{battery}$ | バッテリの余裕の項の重み | `0.10` |
| `weights.cpu_time` | $w_\mathrm{cpu}$ | CPU 時間の項の重み | `0.05` |
| `cpu_time.startup_allowance_s` | $B_\mathrm{startup}$ | インタプリタの起動と戦略の読み込みに対する CPU 時間の予算（秒） | `5.0` |
| `cpu_time.per_decision_cycle_s` | $B_\mathrm{cycle}$ | 制限時間内の判断周期1回あたりの CPU 時間の予算（秒） | `0.1` |

同梱の値とチャレンジ問題（制限時間 21600 s，判断周期 60 s）では，CPU 時間の予算は $5 + 0.1 \cdot 360 = 41$ 秒です。

設定は，次の規則を満たさなければなりません。

- すべてのセクションとキーが必要で，形式が定義していないキーとセクションは拒否されます。
- すべての値は有限の数です。
- 重みは負でなく，合計は $10^{-9}$ の範囲で1です。
- `tolerance_fraction`，`startup_allowance_s`，`per_decision_cycle_s` は正です。
- `undeclared_factor` は0から1までです。

規則を満たさない設定に対しては，`ValueError` のサブクラスである `ScoringConfigError` が送出されます。

### 設定の読み込み

| メソッド | 意味 |
|---|---|
| `ScoringConfig.default()` | 同梱の設定 |
| `ScoringConfig.from_toml(data)` | TOML ファイルの `Path`，`str` の TOML テキスト，`bytes` の UTF-8 の TOML から読み込んだ設定 |
| `ScoringConfig.from_dict(data)` | TOML ファイルと同じ構成の辞書から読み込んだ設定 |
| `to_dict()` | TOML ファイルと同じ構成の，JSON に変換できる辞書としての設定 |

`from_toml` は，UTF-8 の TOML ではないデータに対しても `ScoringConfigError` を送出し，
読めないファイルに対しては `OSError` を送出します。
別の設定で評価するには，その設定を `evaluate_submission` または `check_submission` に渡します。

```python
config = ScoringConfig.from_toml(Path("my-scoring.toml"))
evaluation = check_submission(archive, scoring=config)
```

`scoring` を渡さなければ，どちらも `ScoringConfig.default()` を使います。

## 関数

`score_case(outcome, config)` は，1つの `CaseOutcome` の `CaseScore` を返します。
`CaseScore` は次のフィールドを持ちます。

| フィールド | 意味 |
|---|---|
| `value` | 得点 $s$ |
| `gate` | $g$ |
| `accuracy` | $a$ |
| `declaration` | $d$ |
| `completion_time` | $t$ |
| `battery_margin` | $b$ |
| `cpu_time` | $c$ |

`to_dict()` はこれらのフィールドを辞書として返し，`CaseScore.from_dict` はその逆変換です。
`from_dict` は，評価ケースの得点を表さないデータに対して `ValueError` を送出します。
0から1の範囲外の値もこれに含まれます。
`ZERO_SCORE` は，評価指標のない評価ケースの得点です。

`suite_score(scores)` は，`Suite` のすべての評価ケースの `CaseScore` から `Suite` の得点 $S$ を返します。
`CaseScore` が1つもなければ0を返します。

## 得点が現れる場所

- `SubmissionEvaluation.scoring` は，評価の得点の設定です（[提出物の評価](evaluating.ja.md)を参照）。
- `SuiteSummary.score` は `Suite` の得点で，`summary_rows` はこれを小数第2位まで最初に示します。
- `EvaluationResult.scores` は各結果の `CaseScore` を持ち，
  `case_rows(outcomes, scores)` はその `value` の 100 倍を，`Suite` の得点と同じ尺度で `Score` 列に示します。
- 結果文書では，`scoring` が設定を，`summary.score` が `Suite` の得点を，`cases` の各要素の `score` がその `CaseScore` を持ちます。
  評価ケースを省いて絞り込んだ結果文書でも，残した評価ケースの得点と保存された `Suite` の得点はそのまま保たれます。
