# ADR 0025: 学習モジュールの end-to-end 配線（core への少量学習）

- 日付: 2026-06-14
- ステータス: 提案（Step 3 テストレビューで確定）
- 関連: ADR 0022（core ランナー）、ADR 0019（F-010 scene HGF 学習）、ADR 0020（F-009 t3 学習）、
  ADR 0024（dev-eval 結線修正）、ADR 0012（指標式）、F-014（過学習ガード）、
  `scripts/run_cv_train.py` / `reports/cv-train-*.md`（学習効果の CV 測定）

## 背景

ADR 0019/0020 は scene/t3 に「少量学習」（`fit(practice_data)`）を設計したが、`core.run_supreme` は
**未学習の既定値**で動かしている（scene は `scene_mod.fit([])`＝空、t3 は `default_params()`）。
end-to-end で一度も学習していない。CV 測定（`scripts/run_cv_train.py`・lineage-disjoint 5-fold）で、
**学習が held-out で既定を上回る**ことを確認した:

- scene_regime: 0.324 → **0.557**（+0.233・全5fold正・過学習0＝頑健に汎化）。
- t3_hypothesis: 0.357 → **0.410**（+0.052・fold ばらつき大・中程度の過学習）。

現状は測定された改善を捨てている。これを配線する。

## 決定（提案）

### 決定1: core に学習経路を追加（後方互換）

- `core.fit_supreme(practice_scenarios, gt) -> SupremeParams`: 練習シナリオ（PSO 入力 + 8層 GT）から
  各モジュールの学習入力を **core の実経路と一致させて**組み立て（t3: argmax mode 系列 + reset + gt /
  scene: health 信号系列 + gt）、`t3.fit` / `scene.fit` で決定的に学習する。返り値 `SupremeParams` は
  学習済み t3/scene params を保持。
- `core.run_supreme(snaps, params=None)` / `run_supreme_scenarios(scenarios, params=None)`: `params` が
  `SupremeParams` なら学習済みで実走、**`None` なら現状の既定挙動**（後方互換）。`config` は不変。

### 決定2: 学習対象は t3 / scene のみ

quality は `fit` 無し＝固定ルール（ADR 0014・h_q≥0.93）で既に win のため学習対象外。mode/relation/
strong は本 ADR のスコープ外（必要なら別 ADR）。

### 決定3: 方法論（過学習を出さない）

- **deploy**: 全練習データ（現状 v021_core）で学習した params を使う。
- **正直な精度**: **CV held-out**（lineage-disjoint）を正準とする。学習後の in-sample 再代入（train=eval）は
  楽観方向に歪むため、報告では **in-sample（楽観）と CV held-out（正直）を併記**する。
- **封印は不可触**（最終 verdict 用）。練習データの増強（F-003・AI 生成 GT・穴5）は**学習信号としてのみ**
  使い、最終 verdict には使わない。
- **F-014 ガード**: learnable param 数（t3=6, scene=3）≪ 練習採点フレーム数。configurable な k で検査。
- 決定的（乱数・時刻なし）・stdlib のみ・v1.4 語彙。

### 決定4: 後方互換の担保

`params=None` 既定で既存 740 テストの挙動を一切変えない。学習経路（fit_supreme・params 注入）は新規テストで
固定する。

## 影響

- 実装: `src/supreme/core.py` に `fit_supreme` / `SupremeParams` 追加・`run_supreme(*, params=)` 拡張。
  t3/scene の既存 `fit` を再利用。モジュール本体は不変。
- 期待（CV held-out 推定）: scene **win 反転**（~0.557 > baseline 0.543）、t3 改善（~0.410・まだ lose）。
  弱5 win3→**win4/lose1**（残 lose は t3 のみ）。**すべて練習/CV 上**＝封印 verdict ではない。
- 残件: t3 の held-out ばらつき（過学習傾向）は練習データ拡充（F-003）で緩和余地。最終確定は封印（F-013）。

## 追記（監査 2026-06-14・`reports/audit-20260614-2005-Phase1.md`・pass / done可）

- **P1-R4（Phase 1b・将来）**: 本 Phase は「学習を core に配線する capability」まで。**dev-eval（`run_dev_eval.py`）と封印評価（`sealeval.run_sealed_evaluation`）は依然 `params` 省略＝既定（未学習）で動く**。学習の利得を実測・封印 verdict に効かせるには、評価経路へ `core.fit_supreme(練習)` → 学習 params を注入する配線が別途要る（Phase 1b）。
- **P1-R2（記録）**: Phase1 予算テストの `data` 数は採点フレーム数（合成 fixture=24）を使う。SPEC.md §F-014（「data 数=練習用シナリオ件数」）とは定義が異なる（本 fixture では合格・本番 data~200 でも余裕）。将来 fixture 変更時の誤判定に注意。
- **scene 計上 9→3**: U24（学習で更新される連続値のみ計上）と `scene.fit` 実態（閾値3のみ更新・HGF 固定）に基づく正当な訂正（監査確定）。将来 HGF を学習対象に含める設計に変えるなら計上の更新と F-014 予算の再確認が要る。
- **honest な学習利得（CV held-out・`run_cv_train.py`）**: scene 0.324→**0.557**（win 反転・vs baseline 0.543）、t3 0.357→0.410（改善・まだ lose）。配線を評価経路に展開（Phase 1b）すれば弱5は **win4/lose1**（残 lose=t3）になる見込み。すべて練習/CV 上＝封印 verdict ではない。
