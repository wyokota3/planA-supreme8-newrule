# 学習効果 CV 分析レポート — t3.fit / scene.fit は held-out で既定を上回るか

- 生成時刻: 2026-06-14 22:00
- 対象: v021_core 20シナリオ(各独立 root・lineage-disjoint)
- PSO 入力: planA-baseline/scenarios/v021_core ／ GT: n04-feat/scenarios/v021_core(catalog 1.4.0)
- 経路: core の実入力と一致する mode_seq(t3)/ health 信号(scene)を抽出して fit/分類
- 手法: 決定的 5-fold CV(scenario_id ソート順 4件ずつ・乱数なし)
- **本レポートは分析専用**: src/supreme/*.py(core/モジュール/テスト)は無改変。
  supreme.* 公開 API + core 内部関数(_quality_obs_raw_logits / _scene_health_signal 等)の
  import 再利用のみ。baseline は import していない(独立性)。

## 結論(学習は held-out で効くか)

| モジュール | held-out 既定 acc | held-out 学習 acc | Δ(学習−既定) | 学習は効くか |
|---|---:|---:|---:|---|
| t3_hypothesis | 0.3905 | 0.4429 | +0.0524 | **yes(+0.0524)** |
| scene_regime | 0.3238 | 0.5571 | +0.2333 | **yes(+0.2333)** |

> 「学習を core へ配線する価値」: held-out で学習 acc が既定 acc を上回る(Δ>0)モジュールは
> 配線の価値あり。上回らない(Δ≤0)モジュールは「学習は効かない=不振の原因は別」を示唆する。
> held-out 採点分母: t3=210 フレーム / scene=210 フレーム

## t3_hypothesis: CV held-out acc(既定 → 学習)と fold 別

| fold | validation シナリオ | 採点分母 | 既定 acc | 学習 acc | Δ |
|---|---|---:|---:|---:|---:|
| 0 | ns-epi-v021-ns001-boot-sanity, ns-epi-v021-ns002-conv-approach, ns-epi-v021-ns003-siren-danger, ns-epi-v021-ns004-input-degradation | 19 | 0.3684 | 0.3684 | +0.0000 |
| 1 | ns-epi-v021-ns005-anomaly-surprise, ns-epi-v021-ns006-scene-transition, ns-epi-v021-ns007-crowd-ambient, ns-epi-v021-ns008-vehicle-caution | 22 | 0.3182 | 0.3182 | +0.0000 |
| 2 | ns-epi-v021-ns009-quality-recovery, ns-epi-v021-ns010-long-idle, ns-epi-v021-ns011-multi-stress, ns-epi-v021-ns012-vehicle-pass | 28 | 0.4643 | 0.4643 | +0.0000 |
| 3 | ns-epi-v021-ns013-scene-degrading, ns-epi-v021-ns014-quality-safety-latch, ns-epi-v021-ns015-full-coverage, ns-epi-v021-ns016-deep-conversation | 57 | 0.3333 | 0.5614 | +0.2281 |
| 4 | ns-epi-v021-ns017-vehicle-lifecycle, ns-epi-v021-ns018-quality-cycle, ns-epi-v021-ns019-scene-regime-cycle, ns-epi-v021-ns020-sustained-emergency | 84 | 0.4286 | 0.4048 | -0.0238 |
| **held-out 全体** | (5 fold 集約) | 210 | **0.3905** | **0.4429** | **+0.0524** |

## scene_regime: CV held-out acc(既定 → 学習)と fold 別

| fold | validation シナリオ | 採点分母 | 既定 acc | 学習 acc | Δ |
|---|---|---:|---:|---:|---:|
| 0 | ns-epi-v021-ns001-boot-sanity, ns-epi-v021-ns002-conv-approach, ns-epi-v021-ns003-siren-danger, ns-epi-v021-ns004-input-degradation | 19 | 0.1579 | 0.7368 | +0.5789 |
| 1 | ns-epi-v021-ns005-anomaly-surprise, ns-epi-v021-ns006-scene-transition, ns-epi-v021-ns007-crowd-ambient, ns-epi-v021-ns008-vehicle-caution | 22 | 0.4545 | 0.5455 | +0.0909 |
| 2 | ns-epi-v021-ns009-quality-recovery, ns-epi-v021-ns010-long-idle, ns-epi-v021-ns011-multi-stress, ns-epi-v021-ns012-vehicle-pass | 28 | 0.3214 | 0.7500 | +0.4286 |
| 3 | ns-epi-v021-ns013-scene-degrading, ns-epi-v021-ns014-quality-safety-latch, ns-epi-v021-ns015-full-coverage, ns-epi-v021-ns016-deep-conversation | 57 | 0.3509 | 0.4737 | +0.1228 |
| 4 | ns-epi-v021-ns017-vehicle-lifecycle, ns-epi-v021-ns018-quality-cycle, ns-epi-v021-ns019-scene-regime-cycle, ns-epi-v021-ns020-sustained-emergency | 84 | 0.3095 | 0.5119 | +0.2024 |
| **held-out 全体** | (5 fold 集約) | 210 | **0.3238** | **0.5571** | **+0.2333** |

## 参考: in-sample(train=eval=全20)acc と held-out との差(過学習度)

in-sample は学習に使ったデータ自身での acc。held-out との差(in-sample − held-out 学習)が
大きいほど過学習(訓練データへの適合が汎化しない)。

| モジュール | in-sample 既定 | in-sample 学習 | held-out 学習 | 過学習度(in − held 学習) |
|---|---:|---:|---:|---:|
| t3_hypothesis | 0.3905 | 0.5476 | 0.4429 | +0.1048 |
| scene_regime | 0.3238 | 0.5571 | 0.5571 | +0.0000 |

## F-014 ガードレール①(learnable param ≪ train データ)の充足

学習可能パラメータ数(U24: 学習対象の連続値のみ計数)が train フレーム数より十分小さいことを
各 fold で確認する(過学習防止規律)。t3=6個(ロジスティック重み3+バイアス3)、
scene=学習対象の閾値3個(vol_high/persist_high/level_low・HGF param は既定固定)。

| モジュール | fold | learnable param 数 | train 採点フレーム数 | param ≪ data |
|---|---|---:|---:|---|
| t3 | 0 | 6 | 191 | OK |
| t3 | 1 | 6 | 188 | OK |
| t3 | 2 | 6 | 182 | OK |
| t3 | 3 | 6 | 153 | OK |
| t3 | 4 | 6 | 126 | OK |
| scene | 0 | 3 | 191 | OK |
| scene | 1 | 3 | 188 | OK |
| scene | 2 | 3 | 182 | OK |
| scene | 3 | 3 | 153 | OK |
| scene | 4 | 3 | 126 | OK |

> NOTE: t3/scene の `learnable_param_count()` は **学習対象の連続値のみ**(U24・ADR 0018/0019/0020)。
> scene の `learnable_param_count()` は仕様上 9(HGF 6 + 閾値 3)を返すが、本実装の fit が実際に
> 更新するのは閾値 3 個のみ(HGF param は既定固定)。いずれにせよ train フレーム数を遥かに下回り、
> ガードレール①(param < data × k, k=0.5)は十分なマージンで充足する。

## 抽出突合の記録(core の実入力との一致)

抽出した t3 mode_seq / scene signal が core.run_supreme の実入力と一致することを
**全 20 シナリオ**で突合した(1 シナリオでなく全件・確実性のため)。
突合方法: 抽出 mode_seq を `t3.run_t3_sequence(..., default_params())` に流して得た
t3_hypothesis 列が core の view と完全一致 / 抽出 signal を core 同等 params で
`scene.classify_sequence` した regime 列が core の view と完全一致。**全件一致**
(不一致が 1 件でもあれば数字を出さず停止する設計)。

## caveat(厳密性に関する注記)

1. **in-sample 性**: v021_core は F-005 エラー分析(supreme 改良モジュールの開発)に使用済み。
   本 CV の held-out は v021_core 内の分割であり、人手封印(F-013)ではない。汚染ゼロの最終
   verdict ではなく、「学習が CV で汎化するか」の分析である。
2. **scene 既定 = fit([])**: scene には `default_params()` が無く、既定は fit([])(練習データ
   皆無)が返す _SceneParams(grid 先頭閾値)。これが指示の「fit([])相当の既定」。なお core は
   この既定をそのまま使わず persist.nominal と閾値を結線で差し替える(`_SCENE_THRESHOLDS`)が、
   本 CV は「fit が学習する閾値」自体の汎化を測るため、純粋な fit([]) vs fit(train) で比較する
   (core の結線差し替えは学習効果の測定対象でない)。
3. **t3 既定 = default_params()**: core が実際に使う未学習既定そのもの(core.py L526)。
4. **lineage-disjoint**: v021_core 20件は各自が root(generation=0・F-001 境界条件)。
   増強の親子は無いため、scenario_id 単位の分割で train/validation のリネージは非交差。

## fold 構成(決定的・scenario_id ソート順)

| fold | validation シナリオ(4件) |
|---|---|
| 0 | ns-epi-v021-ns001-boot-sanity, ns-epi-v021-ns002-conv-approach, ns-epi-v021-ns003-siren-danger, ns-epi-v021-ns004-input-degradation |
| 1 | ns-epi-v021-ns005-anomaly-surprise, ns-epi-v021-ns006-scene-transition, ns-epi-v021-ns007-crowd-ambient, ns-epi-v021-ns008-vehicle-caution |
| 2 | ns-epi-v021-ns009-quality-recovery, ns-epi-v021-ns010-long-idle, ns-epi-v021-ns011-multi-stress, ns-epi-v021-ns012-vehicle-pass |
| 3 | ns-epi-v021-ns013-scene-degrading, ns-epi-v021-ns014-quality-safety-latch, ns-epi-v021-ns015-full-coverage, ns-epi-v021-ns016-deep-conversation |
| 4 | ns-epi-v021-ns017-vehicle-lifecycle, ns-epi-v021-ns018-quality-cycle, ns-epi-v021-ns019-scene-regime-cycle, ns-epi-v021-ns020-sustained-emergency |

---

_本レポートは supreme.* 公開 API + core 内部関数の import 再利用のみで生成した
(baseline コードは import していない=独立性)。core/モジュール/テストは無改変・分析専用。
2 回走行で held-out acc・fold 別 acc・param 数が完全一致することを確認済み(決定性)。_
