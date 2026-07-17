# ADR 0041(v1.6): env_start を QoS 振動(detrend 残差分散)で回収

- 日付: 2026-06-25
- ステータス: 採用
- 関連: F-009(t3)・`ROADMAP-v1.6.md`(C 項)・ADR 0037(t3 v1.5 override)・ADR 0040(conv link type)。
- エビデンス: coverage_v2 train/eval(held-out)・全835テスト緑。

## 背景

ADR 0037 で env_start は **t3=0.000**(分離信号なし)として未回収だった。roadmap C は「QoS 振動 →
`qos_variance`(契約 v1.6 信号)」を仮説したが、**生分散では分離しない**ことが判明:

| t3 | 生QoS窓分散(mean) | 代表 QoS 列 |
|---|---:|---|
| hazard_declining | **0.0134(最高)** | `[0.95,0.80,0.65,0.50]` 単調降下(幅0.45) |
| env_start | 0.0115 | `[0.72,0.47,0.72,0.47,0.72]` 振動(幅0.25) |

単調降下は振動より**生分散が大きい**(変化幅が大)ため生分散では env_start↔hazard_declining が逆転する。
真の弁別は **トレンド除去後の残差分散(detrend variance)**:

| t3 | detrend分散(mean) | 備考 |
|---|---:|---|
| **env_start** | **0.0064(最高)** | 振動=平均回帰=残差大 |
| traffic_unstable | 0.0035 | 上位 tier(approach)で先取り |
| conv_participating | 0.0025 | 上位 tier(speech)で先取り |
| hazard_declining | **0.0000** | 単調=直線=残差ゼロ |
| uncertain/sustained/quiet/alert | ≈0 | 低変動 |

## 決定

`core._t3_v15_episode_override` に **最下位 tier** として追加(speech→QoS→approach の後):
- 窓 `[ts-3.0,ts]∩episode` の QoS を OLS detrend し残差分散を算出(`_qos_detrend_var_frame`・点<3 は 0)。
- episode 全フレーム平均が `>= 0.003` → **env_start**。
- 上位 tier(conv/uncertain/traffic)が優先するため traffic/conv の振動フレームと競合しない。

**信号は観測 QoS から supreme が算出**(契約変更不要)。conv(ADR 0040)が既存 link を使ったのと同型で、
本 override は既に speech/approach/QoS 平均を集約しており detrend 分散も同じ観測列から得られる。roadmap C の
「契約 v1.6 で qos_variance を追加」仮説を**観測計算で代替**(契約面を増やさない・より誠実)。閾値 0.002〜0.004 で
結果不変=振動/非振動の構造境界(knife-edge 合わせ込みでない)。ラベル非依存(非循環)。episode 不在(v1.4)は不変。

## 結果(train / eval・held-out)

| | TRAIN | EVAL(held-out) |
|---|---:|---:|
| t3_hypothesis | 0.689→**0.738** | 0.681→**0.731** |
| **8層平均** | 0.781→**0.787** | 0.776→**0.783** |

- env_start **0→42 回収**(eval)・残 32 は traffic 寄り(approach 重なり・上位 tier 優先の設計上限)。
- hazard_declining/他クラスへの巻き込みなし(detrend がゼロで除外)。
- eval が train と同等に伸び=**過適合でない**。全835テスト緑(+env_start v16 4件)。seal 合わせ込みなし。

## 限界(正直に)

- env_start の残 32f は approach も高く traffic と重なる(上位 tier 優先)。これ以上の弁別は過適合のため不追求。
- hazard_declining は依然回収不能(単調降下=観測に「hazard 後退」情報なし=原理天井・ROADMAP D)。
- 残 mode 伸びしろは side_rear_caution(生成器が rear 幾何未 emit・ROADMAP B)。
