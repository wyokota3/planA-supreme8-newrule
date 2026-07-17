# t3 grid 境界張り付き診断 + 候補拡張 CV held-out 検証

- 生成時刻: 2026-06-15 07:47
- 対象: v021_core 20シナリオ(各独立 root・lineage-disjoint 5-fold)
- 目的: conv-B と同じ筋で t3 の他学習 param に grid 境界張り付きがあるか・あれば候補拡張で CV held-out が改善するか(改善のみ採用・無ければ天井)
- **分析専用**: src/supreme/*.py 無改変。fit の grid 定数を実行中メモリのみモンキーパッチして CV を再測定(ファイルは書き換えない)。
- run_cv_train.py の CV 基盤(fold 分割・抽出突合・micro_acc)を import 再利用・決定的。

## 1. 現行 grid

| param | grid |
|---|---|
| `w_conv_ratio` | (2.0, 4.0, 6.0, 8.0, 10.0) |
| `w_switch_rate` | (2.0, 4.0, 6.0, 8.0, 10.0) |
| `w_flip_accum` | (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 6.0) |
| `bias_conv` | (-3.0, -2.0, -1.0, 0.0) |
| `bias_traffic` | (-3.0, -2.0, -1.0, 0.0) |
| `bias_quiet` | (0.0, 0.25, 0.5, 1.0) |

## 2. fold 別 fit 選択値(現行 grid)

| fold | `w_conv_ratio` | `w_switch_rate` | `w_flip_accum` | `bias_conv` | `bias_traffic` | `bias_quiet` |
|---|---|---|---|---|---|---|
| 0 | 10 | 2 | 0.5 | -1 | -2 | 0.5 |
| 1 | 10 | 2 | 0.5 | -1 | -2 | 0.5 |
| 2 | 8 | 6 | 0.5 | -1 | -2 | 0.5 |
| 3 | 10 | 2 | 0.5 | -1 | -2 | 0.5 |
| 4 | 8 | 2 | 0 | -1 | -2 | 0.5 |
| in-sample(全20) | 10 | 2 | 0.5 | -1 | -2 | 0.5 |

## 3. grid 境界張り付き(min/max)

| param | grid min | grid max | 下限張り付き fold | 上限張り付き fold |
|---|---:|---:|---|---|
| `w_conv_ratio` | 2 | 10 | — | 0, 1, 3 |
| `w_switch_rate` | 2 | 10 | 0, 1, 3, 4 | — |
| `w_flip_accum` | 0 | 6 | 4 | — |
| `bias_conv` | -3 | 0 | — | — |
| `bias_traffic` | -3 | 0 | — | — |
| `bias_quiet` | 0 | 1 | — | — |

> 「張り付き」= その fold の fit が grid の最小値(下限)または最大値(上限)を選んだ= 探索空間が狭くて fit が最適に届かない疑い(conv-B 前の w_flip が下限張り付きだったのと同型)。

## 4. baseline(現行 grid)の CV held-out / in-sample

| 指標 | 既定 | 学習 |
|---|---:|---:|
| held-out | 0.3952 | 0.5381 |
| in-sample | 0.3952 | 0.5381 |
| overfit gap(in − held 学習) | | +0.0000 |
| held-out 採点分母 | | 210 |

## 5. 境界張り付き param の拡張 → CV 再測定(1 param ずつ)

| 拡張 param | 方向 | 追加候補 | held(base→new) | Δheld | gap(base→new) | Δgap | 採用? |
|---|---|---|---|---:|---|---:|---|
| `w_conv_ratio` | upper | [12.0, 14.0] | 0.5381→0.5095 | -0.0286 | +0.0000→+0.0286 | +0.0286 | 不採用 |
| `w_switch_rate` | lower | [0.0, 1.0] | 0.5381→0.5381 | +0.0000 | +0.0000→+0.0000 | +0.0000 | 不採用 |

> 採用条件(指示): held-out が改善(Δheld>0)し、かつ overfit gap が拡大しない(Δgap≤0)。両立しなければ不採用(過適合 or 天井)。

## 6. 判定

**採用候補なし = t3 は現行 grid で CV 天井**。

境界張り付き param への候補拡張をすべて試したが、CV held-out が改善する拡張は1 件も無かった(または改善しても overfit gap が拡大=過適合)。
conv-B(`_W_FLIP_GRID` 拡張)で得た 0.5381 が現行データでの t3 の CV 天井であり、これ以上の grid 拡張は in-sample への合わせ込み(過適合)にしかならない。

→ **src は無改変(revert 不要・そもそも書いていない)**。honest に「t3 はこれ以上 CV で詰められない」と報告する。

---

_分析専用(src 無改変・baseline 非 import・決定的)。grid は実行中メモリのみモンキーパッチし測定後に復元。CV 基盤は run_cv_train.py を再利用。_