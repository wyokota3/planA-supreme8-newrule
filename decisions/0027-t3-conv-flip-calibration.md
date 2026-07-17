# ADR 0027: t3 conv/traffic 較正 — flip ペナルティ grid 拡張（CV 検証）

- 日付: 2026-06-14
- ステータス: 採用（CV held-out 検証・監査 pass）
- 関連: ADR 0020（F-009 t3 学習）、ADR 0025（学習配線）、ADR 0026（Phase4 h_q ゲート）、
  `reports/conv-diagnose-20260614-2247.md`（診断）、`reports/cv-train-20260614-2254.md`（CV 採用根拠）、
  `reports/audit-20260614-2256-conv-B.md`（監査 pass）

## 背景

弱5の唯一の lose は t3_hypothesis。診断（`conv-diagnose`）で **conv_participating 取りこぼし（GT 29件中 t3 正答 5・主誤分類先 traffic_unstable 16）の主因は (B) t3 conv/traffic 学習境界の較正**と確定。上流 mode は conv を 72% emit・会話証拠は入力に 100% 在り、genuine（証拠なし）でも mode 潰しでもない。

真因＝`classify_t3` の `w_flip_accum`（既定 4.0）が **単一 mode 切替（flip_accum=1）で traffic_score を +4 底上げ**し、持続 conv（conv_ratio 0.7）を負かす。fit はより低い flip ペナルティを欲するが、grid `_W_FLIP_GRID=(0.5,1.0,2.0,4.0,6.0)` の下限 0.5 で頭打ち（fold3 が 0.5 張り付き）。

## 決定

`_W_FLIP_GRID` に低候補 `0.0, 0.25` を追加（`(0.0,0.25,0.5,1.0,2.0,4.0,6.0)`）。**fit の探索空間を広げただけで learnable param 数は 6 のまま不変**（F-014 維持）。`classify_t3` の係数構造・特徴は無変更（単調係数のまま・GT 個別 if や新特徴は足さない）。上流 mode は無改変（(A) は偽陽性ゼロに直せず＝過適合のため見送り・診断で再確認）。

## 過適合でない根拠（CV held-out 検証）

- lineage-disjoint 5-fold CV held-out t3_hypothesis: **0.4429 → 0.5333（+0.0904）**。
- **overfit gap +0.1047 → 0.0000**（held-out == in-sample 学習）。全 fold で Δ≥0・regression なし。
- 機序は上流 mode 無改変条件のプローブで確認（flip ペナルティ低下で取りこぼし解消）。
- in-sample 最大化ではなく held-out で汎化が確認できたため採用（監査 pass）。

## 影響

- t3 CV held-out 0.4429 → 0.5333。baseline 0.629 には未達（−0.096）だが大幅接近（前回 −0.272）。
- 既定経路（`default_params`・`run_supreme(params=None)`）は fit grid に到達しないため dev-eval 既定列・他層・790テストは完全不変（後方互換）。
- 残る t3 誤りは (A) 上流 mode の弱会話取りこぼし（conv_request 専用証拠が v021_core に無く speaking_link 流用は偽陽性ゼロにできない＝過適合）と quiet_stable 11件で、**t3 較正では回復不能**。最終確定は封印（F-013）。

## 技術的負債（監査記録・低優先）

- **座標降下初期値の index 依存**: `t3.fit` の `best` 初期値が `_W_FLIP_GRID[2]` を参照するため、grid 先頭に候補を足した副作用で w_flip_accum の初期値が 2.0→0.5 に無言で移動した。CV 採用根拠は「候補拡張」と「初期値移動」の合成効果（分離していない）だが、CV 実測が合成効果込みで汎化（gap=0）を示すため判定は不変。**将来 grid を再編する際は初期値を値由来にする等で index 依存を解消すること**（`test_F009_fit.py` は fit 出力値を契約せず決定性のみ見るためテストでは検出されない）。
