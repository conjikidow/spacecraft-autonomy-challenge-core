# チャレンジ問題

[English](challenge.md) | **日本語**

`spacecraft_autonomy_challenge.challenge` は，チャレンジ問題とその公開シナリオを定義します。
数値はすべて，[宇宙機モデル](spacecraft-model.ja.md)で説明する簡易モデル向けの値です。

```python
from spacecraft_autonomy_challenge.challenge import problem, scenario, scenario_names

print(scenario_names())
nominal = scenario("nominal")
```

`problem()` は，すべてのシナリオが共有する `Problem` を返します。
`scenario(name)` は新しい `Scenario` を構築します。
未知の名前を渡すと，利用可能な名前を列挙した `KeyError` を送出します。

## 問題

| 項目 | 値 |
|---|---|
| 目標 Δv | 10 m/s |
| 制限時間 | 21600 s |
| 判断周期 | 60 s |
| スラスタの加速度 | 0.001 m/s²（両スラスタ） |
| スラスタの消費電力 | 30 W（両スラスタ） |
| スラスタの発熱 | 40 W（両スラスタ） |
| ホイール角運動量変化率 | +0.002 Nms/s（`THRUSTER_1`），−0.002 Nms/s（`THRUSTER_2`） |
| 発電電力 | 60 W |
| バス負荷 | 40 W |
| ヒータの消費電力 | 10 W |
| バッテリ容量 | 100 Wh |
| 熱容量 | 2000 J/K |
| 熱コンダクタンス | 0.5 W/K |
| シンク温度 | −10 °C |
| 噴射可能温度の下限 | 0 °C |
| 推進系温度の上限 | 60 °C |
| バッテリ蓄電量の下限 | 10 Wh |
| ホイール角運動量の絶対値の上限 | 5 Nms |
| 初期温度 | 20 °C |
| 初期バッテリ蓄電量 | 80 Wh |
| 初期 Δv と初期ホイール角運動量 | 0 |
| ヒータと推進の初期状態 | オフ |

## シナリオ

### `nominal`

宇宙機は公称モデルどおりに振る舞います。
`Modifier` はありません。

### `thruster-degradation`

`nominal` に，`ThrusterEfficiency(THRUSTER_1, factor=0.8, onset_time_s=3600.0)` という `Modifier` を1つだけ加えたシナリオです。
3600秒以降，`THRUSTER_1` は公称の80%の加速度しか出せなくなります。
消費電力，発熱，ホイール角運動量変化率は変わりません。
`MissionBrief` には公称パラメータがそのまま含まれるため，戦略がこの変化に気付く手段はテレメトリしかありません。
