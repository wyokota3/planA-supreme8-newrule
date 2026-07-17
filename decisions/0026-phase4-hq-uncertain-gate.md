# ADR 0026: Phase 4 — 観測式/HGF(h_q)を t3 へ結線する uncertain_context ゲート

- 日付: 2026-06-14
- ステータス: 採用
- 関連: ADR 0014(quality 較正・観測式/HGF の h_q 過敏を申し送り)、ADR 0020(F-009 t3 構成)、
  ADR 0022(F-基盤-001・core 結線)、ADR 0025(学習の core 配線)、
  `reports/phase4-hgf-diagnose-after.md`(h_q 分布・死配線診断の計測根拠)、
  `reports/cv-train-20260614-1945.md`(ゲート結線**前** CV held-out)、
  `reports/cv-phase4-after.md`(ゲート結線**後** CV held-out)、
  `reports/phase4-substantiate-20260614-2216.md`(**偽陽性ゼロ・tau plateau・ゲート利得の実測**・監査 R2/R3 裏付け)
- 決定者: Phase 4 診断(観測式/HGF が t3 に効くかの切り分け)

## 背景・狙い

弱5項目の唯一の lose は t3_hypothesis。観測式/HGF は h_q を作り core 経由で t3 の posterior
入力へ流れる。Phase 4 は「観測式/HGF 改善が t3 を上げるか、構造バグがあるか」を **src 無改変の
診断** で切り分けた。

## 診断結果(証拠付き・3点)

`scripts/run_phase4_hgf_diagnose.py`(分析専用・baseline 非 import・決定的)で計測した。

### 1. h_q 過敏(ADR 0014 積み残し)は**解消済み**

GT quality クラス別の h_q 分布:

| GT quality | n | h_q median | min | max |
|---|---:|---:|---:|---:|
| GOOD | 154 | 0.9407 | 0.5944 | 0.9491 |
| DEGRADED | 32 | 0.8267 | 0.1849 | 0.9418 |
| BLOCK | 24 | 0.2576 | 0.0023 | 0.8241 |

ADR 0014 が記録した「DEGRADED 相当で h_q を ~0 まで潰す過敏(v1.3 で DEGRADED max h_q=0.026)」は
supreme 独立実装の現観測式/HGF では**起きていない**(DEGRADED median 0.83)。h_q は品質クラスで
良好に分離する。→ **観測式/HGF の係数は健全。較正対象ではない。**

### 2. h_q は t3 分類器へ**届いていない**(構造潰し=死配線)

感度実験(`step` に渡す mode 列の posterior=h_q だけを 0/1 に振る):

- **直接経路: 0 / 420 フレーム** — posterior を 0→1 に振っても t3 出力は一切変わらない。
  `episode_features` は posterior を `posterior_mean/var/trend` に集約するが、`classify_t3` も
  `_rule_hypothesis` もそれを**一度も読まない**。観測式/HGF が作る h_q が t3 判別へ構造的に届いて
  いない(ADR 0022 が surround_activity で潰した結線ミスと同型の死配線)。
- 間接経路 h_q→mode→t3: 11 mode / 22 t3 フレームのみ(`core._mode_logits` の h_q<0.5→env_change
  経路だけが唯一の h_q→t3 経路)。

### 3. h_q の証拠品質: 大半の t3 クラスは h_q で分離不能・例外が uncertain_context

GT t3 クラス別 h_q 中央値は quiet/conv/traffic/env/crowd/alert いずれも ≈0.9 で**分離不能**。
唯一 **uncertain_context(h_q 中央 0.087・max 0.530)** が低 h_q に強く偏る。実フレームを精査すると、
GT=uncertain_context の 9 件は **BLOCK/DEGRADED 品質の低 h_q** に集中し、supreme は h_q<0.5→env_change
mode→env_start/env_shift と**過剰断定**していた(観測劣化を「環境変化」と誤読)。

## 判定: (A) 構造バグの結線修正 + CV 検証で確認(過適合なし)

「観測が劣化して文脈を断定できない」ことの正準ラベルは v1.4 T3 語彙の **uncertain_context**。
観測式/HGF(h_q)は健全で、欠けていたのは「h_q→t3 の結線」だった。env_start/env_shift は
core が h_q<0.5 で積む観測劣化シグナルから立つので、h_q が下限を割るフレームの env 断定は
過剰であり uncertain_context が正しい。

## 決定: t3.step に観測品質下限ゲート(env 過剰断定のみ是正)

`step` で base 仮説確定後、**posterior(h_q)< 0.40 ∧ base ∈ {env_start, env_shift}** のとき
hypothesis を uncertain_context に書き換える。

- **env 系のみを対象**(quiet/conv/traffic/安全警戒系は触らない)。これにより mode posterior の
  低い静穏フレーム(観測品質でなく静穏)を巻き込まず、**偽陽性ゼロ**。
- 閾値 0.40 は固定構造閾値で **学習対象でない**(U24・既存 `_RULE_*` 閾値と同格)。
  `learnable_param_count()` は 6 のまま(**F-014 予算 t3=6/scene=3/計 9 ≪ 100 不変**)。
- 閾値 0.40 の根拠: GT=uncertain の h_q max 0.530、真 env の h_q min 0.6582(env_start)/0.7384
  (env_shift)、GOOD 品質 h_q ≥ 0.594。0.40 は uncertain と env/GOOD を分離する谷
  (v021_core への合わせ込みでなく品質クラス分離点)。
  **tau スイープ実測**(`reports/phase4-substantiate-20260614-2216.md` 計測2・lineage-disjoint
  5-fold CV held-out 学習 acc): tau∈**[0.35, 0.55]** の 5 点で **held-out acc = 0.4429 で同値の平坦域**
  (tau=0.30 のみ 0.4381 へ低下)。閾値をこの域で振っても held-out 採点は変わらない=過適合でない。
  (※監査前 ADR は平坦域を tau∈[0.35,0.50] と狭く記載していたが、実測の平坦域はより広い [0.35,0.55]。
  ここは実測値に合わせて訂正した。)

## 効果(CV held-out が正準・lineage-disjoint 5-fold)

| 層 | held-out 既定 before→after | held-out 学習 before→after |
|---|---|---|
| **t3_hypothesis** | 0.3571 → **0.3905** | 0.4095 → **0.4429**(+0.0333) |
| scene_regime | 0.3238 → 0.3238 | 0.5571 → 0.5571(不変) |

ゲート利得(学習 0.4095→0.4429 = +0.0333・正確には 86/210→93/210=+7 フレーム)は
`reports/phase4-substantiate-20260614-2216.md` 計測2 で **1 レポート完結**して辿れる
(no-gate=結線前 0.4095 と src 閾値 0.40 = 0.4429 を同一スクリプトで算出)。before/after の
CV は `reports/cv-train-20260614-1945.md`(before)と `reports/cv-phase4-after.md`(after)に対応。
(※監査前 ADR は学習利得を +0.0334 と記載していたが、4 桁丸め値の差し引きによる端数で、
実測の正確値は +0.0333=7/210。ここは実測値に合わせて訂正した。)

- **偽陽性ゼロ**(実測で確定・`reports/phase4-substantiate-20260614-2216.md` 計測1):
  v021_core 全 210 フレームのうち GT=env(env_start 7 + env_shift 15 = 22 件)について、
  「GT=env ∧ posterior(h_q)< 0.40」のフレームは **0 件**。env_start の h_q min=0.6582、
  env_shift の h_q min=0.7384 で、いずれも閾値 0.40 を大きく上回るため、GT=env のフレームは
  構造的に gate を踏まない。よって「正答の env を uncertain へ巻き込む regression = 0」が実測で確定
  (ゲートは観測劣化で立った誤 env のみを是正し、真の env は 1 件も書き換えない)。
- **他層非悪化**(in-sample dev_eval 既定列・before vs after が byte 一致):
  risk_tier 0.9333 / t1 0.9095 / mode 0.6238 / role 0.8714 / relation 0.8381 /
  quality 0.7238 / scene 0.4524 — **t3 以外は全て不変**(ゲートは t3 内のみ)。
- 770 テスト全緑維持(env のみ対象としたことで `test_F009_1_different_reset_list_can_change_output`
  が要求する reset 感度=quiet フレームの分岐を保つ)。
- 決定的(同一系列で 2 回走行完全一致)。

## 残件・正直な限界

- t3 は依然として lose(held-out 0.443 < ours 参考 0.586)。本ゲートは t3 の不振の**一部**
  (uncertain_context の取りこぼし)を観測式/HGF 結線で是正したが、残る誤りは別経路:
  - `hazard_declining`(GT 2件)は supreme 上流が対応 mode を出さず未出力(t3 スコープ外・上流課題)。
  - conv_participating の取りこぼし(GT 29・pred 5)は上流 mode の conv 検出感度の課題で、
    観測式/HGF(h_q)では動かない(h_q は conv クラスで ≈0.9 で分離しない)。
- **観測式/HGF の更なる深掘りは t3 をこれ以上は上げない**(計測3: 残りの t3 クラスは h_q で
  分離不能)。t3 の追加改善は上流 mode 側(conv/hazard mode 結線)が震源で、本 Phase の
  観測式/HGF スコープ外。honest な結論として申し送る。
