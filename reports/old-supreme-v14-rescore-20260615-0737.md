# 旧 supreme(l04-ours)v1.4 全 8 層 再採点 — 新 supreme との apples-to-apples 比較

- 生成時刻: 2026-06-15 07:37
- 対象: v021_core 20 シナリオ・210 フレーム(in-sample・封印 verdict ではない)
- 旧 supreme 予測: `results/trace/trace.json` の per-frame `view`(=l04-ours の権威 per-frame 予測)
- GT: n04-feat/scenarios/v021_core(ADR 0006 で v1.4 正準化・trace.json 埋め込み gt は使わない=混在の元)
- 新 supreme: PSO→core.run_supreme→v1.4 view(run_dev_eval ロジック再利用・既定列＋学習層 in-sample/CV held-out)
- 採点: `harness.canonical_metric_spec()`(8 層 micro acc・完全一致・NA 分母除外)を **新旧で完全に同一**に適用
- src/supreme・テスト無改変。決定的・stdlib + pyyaml。baseline コードは import しない。

## 0. 結論サマリ

- **旧 supreme を v1.4 で再採点した overall(8 層単純平均)= 0.7607**。
- 新 supreme(既定)overall = 0.7423、新 supreme(学習 in-sample)= 0.7732。
- 既定列での新 vs 旧(同一 v1.4 土俵): 新が優 **2** / 互角 **4** / 旧が優 **2**(δ=0.02)。
- **語彙差の可視化**: per_layer.json(v1.3 採点)と本 v1.4 再採点の差が大きいのは quality_regime と t2_mode(正準化が値を動かす層)。恒等層(risk_tier/t1_state/t2_role/t2_relation/scene_regime)は per_layer.json と一致(GT 側の v1.3 固有値が それらの層に無いため)。
- **正準化不能の層は無し**(旧予測 view の全 8 層が ADR 0006 マッピングで v1.4 語彙集合に 収束)。比較不能層は無い。

## 1. 旧 supreme 予測の構造・語彙(trace.json)

`results/trace/trace.json` は `{scenario_key: [frame, ...]}`。各 frame は `{ts, view, gt, correct, modules}`。**`view` が per-frame の 8 層単一ラベル予測**で、これが旧 supreme(l04-ours)の権威 per-frame 出力である。8 層すべて在る(欠落層は無し)。

> ⚠️ 重要(語彙混在の正体): trace.json に**埋め込まれた `gt` は未正準化の v1.3**である(quality_regime に PASS×32、t2_mode 分布に conv_participation 等)。`l04-ours/per_layer.json`(ファイルには catalog 1.4.0 と記載)は、この **v1.3 view を v1.3 gt で採点**した値であり、**採点土俵は v1.3**。本分析は view も GT も v1.4 へ正準化し直す。

| 層 | 旧 view 生語彙(v1.3) | 正準化後(v1.4) | 正準化 | 8 層在/欠 |
|---|---|---|---|---|
| risk_tier | caution, danger, info | caution, danger, info | 恒等 | 在(欠落 0) |
| t1_state | approach, depart, idle, pass | approach, depart, idle, pass | 恒等 | 在(欠落 0) |
| t2_mode | alert_observation, conv_ongoing, conv_participation, emergency, env_change, forward_caution, quiet_standby, surround_activity | conv_ongoing, emergency, env_change, forward_caution, quiet_standby, side_rear_caution, surround_activity, uncertain | ADR0006 2クラスリネーム | 在(欠落 0) |
| t2_role | source_alarm, source_speech, source_vehicle, unknown | source_alarm, source_speech, source_vehicle, unknown | 恒等 | 在(欠落 0) |
| t2_relation | approaching, grouped, near_user | approaching, grouped, near_user | 恒等 | 在(欠落 0) |
| t3_hypothesis | conv_participating, crowd_tendency, env_shift, env_start, quiet_stable, sustained_alert, traffic_unstable, uncertain_context | conv_participating, crowd_tendency, env_shift, env_start, quiet_stable, sustained_alert, traffic_unstable, uncertain_context | 恒等 | 在(欠落 0) |
| quality_regime | BLOCK, DEGRADED, GOOD, PASS | BLOCK, DEGRADED, GOOD | ADR0006/0005 順位シフト(+native BLOCK) | 在(欠落 0) |
| scene_regime | CHANGING, DEGRADING, STABLE | CHANGING, DEGRADING, STABLE | 恒等 | 在(欠落 0) |

- 旧 view の quality_regime は v1.3 4 クラス(GOOD/PASS/DEGRADED/**BLOCK** を native 出力)。順位シフト GOOD→GOOD / PASS→DEGRADED / DEGRADED→BLOCK に加え、native BLOCK は最重度 BLOCK へ写す(順位保存・run_quality_diagnose._B_REMAP_V14 と同一)。
- 旧 view の t2_mode は v1.3 で `alert_observation`(→side_rear_caution)・`conv_participation`(→uncertain)を含む。他 8 クラスは恒等。
- 他 6 層は ADR 0006 にリネーム規定が無く恒等。**正準化後の値が v1.4 語彙集合に収まることを各層で検証済み**(収まらない値が出れば数字を出さず停止する設計)。**全層収束=正準化不能層なし**。

## 2. 旧 supreme(v1.4 再採点)全 8 層 — per_layer.json(v1.3 採点)との差

> per_layer.json(v1.3 採点)= 旧 view を **未正準化 v1.3 GT** で採点した値。本列(v1.4 再採点)= 旧 view も GT も v1.4 正準化して採点。差 = **採点語彙差そのもの**。

| 層 | 旧 v1.4 再採点 | (correct/nonnull) | per_layer.json(v1.3) | Δ(v1.4 − v1.3) | 差の主因 |
|---|---:|:---:|---:|---:|---|
| risk_tier | 0.9333 | 196/210 | 0.9333 | +0.0000 | 恒等層(GT に v1.3 固有値なし=不変) |
| t1_state | 0.9095 | 191/210 | 0.9095 | -0.0000 | 恒等層(GT に v1.3 固有値なし=不変) |
| t2_mode | 0.6238 | 131/210 | 0.6238 | -0.0000 | mode リネーム(GT 側 argmax 正準化の影響) |
| t2_role | 0.9333 | 196/210 | 0.9333 | +0.0000 | 恒等層(GT に v1.3 固有値なし=不変) |
| t2_relation | 0.7476 | 157/210 | 0.7476 | +0.0000 | 恒等層(GT に v1.3 固有値なし=不変) |
| t3_hypothesis | 0.5857 | 123/210 | 0.5857 | +0.0000 | 恒等層(GT に v1.3 固有値なし=不変) |
| quality_regime | 0.8238 | 173/210 | 0.7619 | +0.0619 | 順位シフト(PASS/DEGRADED の意味が新 GT と入替) |
| scene_regime | 0.5286 | 111/210 | 0.5286 | +0.0000 | 恒等層(GT に v1.3 固有値なし=不変) |
| **overall(8 層平均)** | **0.7607** | — | 0.7530 | +0.0077 | — |

## 3. 新 vs 旧(同一 v1.4 土俵)全 8 層比較

> **新旧で v1.4 正準化・採点規約を完全に同一**にした apples-to-apples 比較。新 supreme は既定列(非学習層=確定)＋学習層(t3/scene)は in-sample と CV held-out を併記。判定 δ=0.02。

| 層 | 旧 supreme(v1.4) | 新 supreme(既定) | Δ(新−旧) | 判定 | 新 学習(in-sample) | 新 CV held-out(正直) |
|---|---:|---:|---:|---|---:|---:|
| risk_tier | 0.9333 | 0.9333 | +0.0000 | 互角 | —(学習対象外) | —(学習対象外) |
| t1_state | 0.9095 | 0.9095 | +0.0000 | 互角 | —(学習対象外) | —(学習対象外) |
| t2_mode | 0.6238 | 0.6286 | +0.0048 | 互角 | —(学習対象外) | —(学習対象外) |
| t2_role | 0.9333 | 0.9571 | +0.0238 | 新が優 | —(学習対象外) | —(学習対象外) |
| t2_relation | 0.7476 | 0.8381 | +0.0905 | 新が優 | —(学習対象外) | —(学習対象外) |
| t3_hypothesis | 0.5857 | 0.3952 | -0.1905 | 旧が優 | 0.5381 | 0.4095 |
| quality_regime | 0.8238 | 0.8238 | +0.0000 | 互角 | —(学習対象外) | —(学習対象外) |
| scene_regime | 0.5286 | 0.4524 | -0.0762 | 旧が優 | 0.5571 | 0.5571 |
| **overall(8 層平均)** | **0.7607** | **0.7423** | -0.0185 | 互角 | 0.7732 | — |

- **学習層(t3_hypothesis / scene_regime)の honest 比較は CV held-out 列を見ること**。in-sample 学習列は楽観値(train=eval)。既定列(非学習)は新旧とも確定値。
- 学習層の CV held-out で新 supreme を旧 supreme(v1.4)と比べると:
  - t3_hypothesis: 新 CV held-out 0.4095 vs 旧(v1.4) 0.5857 → Δ=-0.1762(旧が優)
  - scene_regime: 新 CV held-out 0.5571 vs 旧(v1.4) 0.5286 → Δ=+0.0285(新が優)

### 3.1 層別の優劣(既定列・同一 v1.4 土俵)

- **新が優**(2): t2_role, t2_relation
- **互角**(4): risk_tier, t1_state, t2_mode, quality_regime
- **旧が優**(2): t3_hypothesis, scene_regime

## 4. 正準化不能・不整合の honest 報告

- **正準化不能の層: 無し**。旧予測 view の全 8 層が ADR 0006 の文書化済みマッピング(mode 2 クラスリネーム + quality 順位シフト + native BLOCK 最重度写像)で v1.4 語彙集合に収束した。v1.4 集合に収まらない値が 1 つでも出れば数字を出さず停止する設計だが、停止は発生しなかった。
- **欠落層: 無し**(全 210 フレームで 8 層 view が揃う)。比較不能フレームは無い。

- **採点規約の非対称(honest 注記)**: `risk_tier` は本採点(canonical_metric_spec)で 210 全件を分母にする(ADR 0012 決定B)。baseline カタログは短尺 T0 を NA 除外して non-null=125 で測る規約のため、**baseline 値との厳密 apples-to-apples ではない**。ただし本比較は**旧 supreme と新 supreme を同一 spec で測る**ので、新旧間は厳密に揃っている(旧 supreme も新 supreme も同じ 210 分母・同じ NA 規約)。

- **t3_hypothesis / scene_regime の GT 値域**: GT には旧 view が native に出さない値(t3: hazard_declining / alert_required、relation: addressing_user 等)が含まれる。これは正準化の不整合ではなく、**旧アーキが該当クラスを予測しないだけ**(exact-match では正しく不正解計上される)。捏造せず、旧の予測語彙が GT より狭い事実として記録する。

## 5. 自己検査(捏造防止)

- 決定性: harness.score を旧・新(既定/学習)で各 2 回呼び 8 層 acc が完全一致(OK)。
- 新 supreme: `run_supreme_scenarios` を各 params で 2 回走行し view 完全一致(OK)。
- 旧予測 v1.4 正準化: 全 8 層・全フレームで v1.4 語彙集合に収束(停止せず=正準化一意)。
- GT 正準化: run_dev_eval.gt_frame_to_v14_view を再利用(新 supreme 採点と同一の GT 列)。
- フレーム数・ts: 旧予測・GT・新予測の 3 者で全シナリオ一致(不一致なら停止する設計)。

---

_本レポートは supreme.* 公開 API(core / harness)と run_dev_eval の正準化ロジックのみで生成した(baseline コードは import していない)。旧 supreme 予測は trace.json の実測 view(再構成ではない)。src/supreme・テスト無改変・決定的・stdlib + pyyaml。_
