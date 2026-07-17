# (A) 上流 mode 弱会話結線の過適合実証 — in-sample 改善 vs CV held-out 棄却

- 生成時刻: 2026-06-14 23:29
- 経路: run_dev_eval / run_cv_train と同一(PSO→core.run_supreme→v1.4 view、GT→ADR0006 正準化)。
- 目的: 診断 (A)(弱会話 speaking_link を `_mode_logits` に結線)を **過適合承知で一時実装**し、
  in-sample では mode/t3 が上がるが **CV held-out で棄却される(非改善 or 悪化 + 偽陽性)** ことを
  数値で実証する。**(A) は採用しない**(実証後 src/supreme は完全 revert)。
- mode は学習対象でないため held-out = 全 v021_core の直接効果。fold 別 validation 偽陽性で
  「held-out で偽陽性が効く」中身を示す。t3 は fit 込み 5-fold CV held-out。
- 決定的・stdlib + pyyaml・baseline 非 import・観測値のみ(捏造なし)。

## 1. before(現行 core・(A) 未結線)= 基準

- in-sample t2_mode acc = **0.6238** (131/210)
- in-sample t3_hypothesis acc = **0.3905** (82/210)
- t3 CV held-out(既定→学習)= 0.3905 → **0.5333**(分母 210)

## 2. (A) 各変種: in-sample Δ vs CV held-out Δ

| 変種 | in-sample mode Δ | in-sample t3 Δ | CV held-out t3 Δ(学習) | conv 系 mode 偽陽性(全体) |
|---|---:|---:|---:|---:|
| **narrow** | +0.0286 | +0.0381 | -0.0143 | 2 |
| **broad** | -0.0238 | -0.0048 | -0.0476 | 14 |

> in-sample mode Δ / t3 Δ は全 v021_core(210)での既定 params 採点の差(before 比)。CV held-out t3 Δ は 5-fold held-out 学習列の差(before 比)。

## 3.narrow 変種 — 詳細

- in-sample t2_mode: 0.6238 → 0.6524(Δ +0.0286・137/210)
- in-sample t3: 0.3905 → 0.4286(Δ +0.0381・90/210)
- conv 系 mode を立てたフレーム数: 36

### 3.narrowa mode 偽陽性(before 正 → narrow 誤)= 2 件

| sid | idx | GT mode | before(正) | variant(誤) | fold |
|---|---:|---|---|---|---:|
| ns-epi-v021-ns015-full-coverage | 17 | quiet_standby | quiet_standby | conv_ongoing | 3 |
| ns-epi-v021-ns016-deep-conversation | 3 | quiet_standby | quiet_standby | conv_ongoing | 3 |

### 3.narrowb mode 回収(before 誤 → narrow 正)= 8 件

| sid | idx | GT mode | before(誤) | variant(正) |
|---|---:|---|---|---|
| ns-epi-v021-ns002-conv-approach | 3 | conv_ongoing | forward_caution | conv_ongoing |
| ns-epi-v021-ns004-input-degradation | 0 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns004-input-degradation | 1 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns006-scene-transition | 0 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns006-scene-transition | 1 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns009-quality-recovery | 1 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns009-quality-recovery | 4 | conv_ongoing | env_change | conv_ongoing |
| ns-epi-v021-ns016-deep-conversation | 17 | conv_ongoing | quiet_standby | conv_ongoing |

### 3.narrowc t3 CV held-out fold 別(variant・mode 列は (A) 結線後)

| fold | 採点分母 | 既定 acc | 学習 acc | Δ(学習−既定) |
|---|---:|---:|---:|---:|
| 0 | 19 | 0.4737 | 0.5789 | +0.1053 |
| 1 | 22 | 0.4091 | 0.4091 | +0.0000 |
| 2 | 28 | 0.5000 | 0.5000 | +0.0000 |
| 3 | 57 | 0.3860 | 0.5439 | +0.1579 |
| 4 | 84 | 0.4286 | 0.5238 | +0.0952 |
| **held-out 全体** | 210 | **0.4286** | **0.5190** | +0.0905 |

- **before 比 CV held-out t3 学習 Δ = -0.0143**(before 0.5333 → narrow 0.5190)

## 3.broad 変種 — 詳細

- in-sample t2_mode: 0.6238 → 0.6000(Δ -0.0238・126/210)
- in-sample t3: 0.3905 → 0.3857(Δ -0.0048・81/210)
- conv 系 mode を立てたフレーム数: 57

### 3.broada mode 偽陽性(before 正 → broad 誤)= 14 件

| sid | idx | GT mode | before(正) | variant(誤) | fold |
|---|---:|---|---|---|---:|
| ns-epi-v021-ns002-conv-approach | 1 | forward_caution | forward_caution | conv_ongoing | 0 |
| ns-epi-v021-ns007-crowd-ambient | 0 | surround_activity | surround_activity | conv_ongoing | 1 |
| ns-epi-v021-ns007-crowd-ambient | 1 | surround_activity | surround_activity | conv_ongoing | 1 |
| ns-epi-v021-ns007-crowd-ambient | 2 | surround_activity | surround_activity | conv_ongoing | 1 |
| ns-epi-v021-ns007-crowd-ambient | 3 | surround_activity | surround_activity | conv_ongoing | 1 |
| ns-epi-v021-ns007-crowd-ambient | 4 | surround_activity | surround_activity | conv_ongoing | 1 |
| ns-epi-v021-ns015-full-coverage | 16 | quiet_standby | quiet_standby | conv_ongoing | 3 |
| ns-epi-v021-ns015-full-coverage | 17 | quiet_standby | quiet_standby | conv_ongoing | 3 |
| ns-epi-v021-ns016-deep-conversation | 3 | quiet_standby | quiet_standby | conv_ongoing | 3 |
| ns-epi-v021-ns016-deep-conversation | 18 | quiet_standby | quiet_standby | conv_ongoing | 3 |
| ns-epi-v021-ns019-scene-regime-cycle | 6 | surround_activity | surround_activity | conv_ongoing | 4 |
| ns-epi-v021-ns019-scene-regime-cycle | 7 | surround_activity | surround_activity | conv_ongoing | 4 |
| ns-epi-v021-ns019-scene-regime-cycle | 8 | surround_activity | surround_activity | conv_ongoing | 4 |
| ns-epi-v021-ns019-scene-regime-cycle | 9 | surround_activity | surround_activity | conv_ongoing | 4 |

### 3.broadb mode 回収(before 誤 → broad 正)= 9 件

| sid | idx | GT mode | before(誤) | variant(正) |
|---|---:|---|---|---|
| ns-epi-v021-ns002-conv-approach | 2 | conv_ongoing | forward_caution | conv_ongoing |
| ns-epi-v021-ns002-conv-approach | 3 | conv_ongoing | forward_caution | conv_ongoing |
| ns-epi-v021-ns004-input-degradation | 0 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns004-input-degradation | 1 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns006-scene-transition | 0 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns006-scene-transition | 1 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns009-quality-recovery | 1 | conv_ongoing | quiet_standby | conv_ongoing |
| ns-epi-v021-ns009-quality-recovery | 4 | conv_ongoing | env_change | conv_ongoing |
| ns-epi-v021-ns016-deep-conversation | 17 | conv_ongoing | quiet_standby | conv_ongoing |

### 3.broadc t3 CV held-out fold 別(variant・mode 列は (A) 結線後)

| fold | 採点分母 | 既定 acc | 学習 acc | Δ(学習−既定) |
|---|---:|---:|---:|---:|
| 0 | 19 | 0.4737 | 0.4737 | +0.0000 |
| 1 | 22 | 0.1818 | 0.1818 | +0.0000 |
| 2 | 28 | 0.5000 | 0.5000 | +0.0000 |
| 3 | 57 | 0.3860 | 0.5088 | +0.1228 |
| 4 | 84 | 0.3810 | 0.5476 | +0.1667 |
| **held-out 全体** | 210 | **0.3857** | **0.4857** | +0.1000 |

- **before 比 CV held-out t3 学習 Δ = -0.0476**(before 0.5333 → broad 0.4857)

## 4. 結論

- **narrow**: in-sample では mode **+0.0286** / t3 **+0.0381** と取りこぼしを回収して上がる(回収 8 件・FP 2 件)。しかし **CV held-out t3 学習は before 比 −0.0143** と非改善(悪化)。FP 2 件は fold 3 の validation(GT=quiet_standby・ns015 idx17 / ns016 idx3)に落ち、held-out で効く。**in-sample で効くが CV で棄却**の典型。
- **broad**: 結線を広げると in-sample ですら mode **−0.0238** / t3 **−0.0048** と悪化(回収 9 件・FP 14 件)。FP は GT=surround_activity(ns007 crowd_ambient ×5・ns019 scene_regime_cycle ×4=群衆で speaking_link が立つ)と GT=quiet_standby(×4)に集中。**CV held-out t3 学習は before 比 −0.0476** と大きく棄却。fold 1(ns007 を含む)はt3 既定 acc が 0.1818 まで崩れ、broad の mode 汚染が held-out を直撃する。

> 補足: held-out の「既定 acc」も before(0.3905)から narrow 0.4286 / broad 0.3857 へ動く(t3 の mode 列入力自体が (A) で変わるため)。それでも **学習列の before 比**(narrow −0.0143・broad −0.0476)は両変種とも負で、(A) は held-out で改善を生まない。

**総括**: (A)(speaking_link 流用の弱会話結線)は v021_core の取りこぼしに過適合する。narrow は in-sample で改善するが CV held-out で非改善(悪化)、broad は in-sample から悪化する。**いずれも CV が正しく棄却する**。よって (A) は採用しない(本実証後 src/supreme は完全 revert 済み)。

---

_測定専用スクリプト出力(supreme.* 公開 API + core/cv 内部関数の import 再利用のみ・baseline 非 import・決定的)。(A) 結線は実証後 src を完全 revert する。_
