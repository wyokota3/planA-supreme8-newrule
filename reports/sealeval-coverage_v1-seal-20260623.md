# F-013 封印評価（真値）— supreme2 vs baseline / coverage_v1 seal

> **⚠️ 撤回注記（2026-06-26・ADR 0049）**: 本レポートの rule_derived 6層（risk_tier/t1_state/t2_mode/t2_role/
> t2_relation/quality_regime）のスコアは、GT が生成規則 `f`（`gt_derive.py`）の決定的関数であるため
> **仕様適合（spec-conformance）の測定であって能力指標ではない**。本レポートを起点とする系譜
> （0.6305 → … → 0.9424）の能力主張は `decisions/0049-evaluation-contamination-retraction.md` で撤回済み。
> 「真値」の語は能力の意味では読まないこと。能力の非循環指標は intent 層（t3/scene）と独立ラベラ評価のみ。

- 実施: 2026-06-23（オーケストレーター実走・研究者承認のもと封印 seal split を使用）
- 目的: 「封印再計測待ち（真値不明）」を解消する。汚染ゼロの held-out で supreme2 と baseline を**同一8層指標・項目別**に対比し、**真値**を確定する。
- データ: **`wyokota3/N04-scenario-contract@main`（commit `2f3da56`）の `coverage_v1`**。
  - 学習(fit): `coverage_v1/train`（406シナリオ）。封印は学習に一切使わない。
  - 評価(seal): `coverage_v1/seal`（86シナリオ・408フレーム）。**train と lineage-disjoint**（README 保証）＝汚染ゼロ。
- 指標: `EVALUATION.md §3` の8層 **global acc**（= Σ正答 / Σ GT非null・完全一致）。δ_strong=0.02。
- 実装: supreme/baseline とも**本体無変更**。入力正規化のみ（`origin` 既定・`geom` 既定。baseline は gate が知る version `PSO-Snapshot/1.3` を維持、supreme は 1.4）。run 一式は `reports/sealeval-coverage_v1-seal-20260623/`。

## 真値（項目別 verdict）

| 層 | 種別 | baseline | supreme2 | Δ(sup−bas) | verdict |
|---|---|---:|---:|---:|---|
| risk_tier      | 強 | 0.5245 | 0.5245 | +0.0000 | maintained |
| t1_state       | 強 | 0.5490 | 0.5490 | +0.0000 | maintained |
| t2_role        | 強 | 0.5711 | 0.4951 | **−0.0760** | **DEGRADED** |
| t2_mode        | 弱 | 0.1765 | 0.2010 | +0.0245 | WIN |
| t2_relation    | 弱 | 0.5392 | 0.3971 | **−0.1422** | **LOSE** |
| t3_hypothesis  | 弱 | 0.5956 | 0.3505 | **−0.2451** | **LOSE** |
| quality_regime | 弱 | 0.4020 | 0.8015 | +0.3995 | WIN |
| scene_regime   | 弱 | 0.4681 | 0.5172 | +0.0490 | WIN |
| **8層平均**    |    | **0.4782** | **0.4795** | **+0.0012** | ほぼ同点 |

- **弱い5項目**: WIN 3（quality 大勝 +0.40 / scene +0.05 / mode 僅差 +0.02）・LOSE 2（relation −0.14 / t3 −0.25）。
- **強い3項目**: risk_tier・t1_state は **baseline と完全一致**（流用が忠実＝採点健全性の内部検証）。**t2_role は −0.076 で DEGRADED**（強い項目の規約 δ_strong 超の低下＝回帰）。
- **成功目標（弱5全↑ ∧ 強維持）は未達**。

## 正直な解釈

1. **総合はほぼ同点**（supreme 0.4795 vs baseline 0.4782 / +0.0012）。**汚染ゼロの balanced 封印では supreme は baseline を総合で上回っていない**。これは in-sample/CV の楽観（supreme 優勢に見えた）が封印では消えるという、まさに「真値不明」警告が守ろうとしていた事象。
2. **項目別は明暗**: quality は本物の大勝（+0.40・学習配線が効いた）、scene も小勝。一方 **relation と t3 は baseline の規則の方が強い**。t3 supreme=0.350 は train2 の独立 CV（0.356）とほぼ一致＝再現性あり。「t3 天井 = mode の限界」「heuristic_confirmed 61%」の構造的難所が封印でも再現。
3. **role 回帰が重要**: 流用で死守すべき強い項目 role が **baseline 0.571 → supreme 0.495 へ低下**。role を流用のまま据えれば risk/t1 同様に同点のはずが、`_role_evidence` 改変（ADR 0028/0029）が**この封印分布では裏目**。要再検討。
4. **絶対値が低い理由**: coverage_v1 は balanced で難所込み＝v021_core 参照（baseline 0.638 / 旧supreme 0.827）より低く出る。これは過小評価ではなく**より正直**（README §被覆の到達点）。

## 既知の限界（受容）

- **統計的有意性なし（U11）**: 86シナリオの点推定。+0.0012 はノイズ域＝総合は実質タイ。信頼区間なし。
- **合成データ（U13）**: t3/scene GT は intent_derived（設計意図）。実知覚ではない。実世界値ではなく相対指標として読む。
- **正規の SealStore 生涯1開封セレモニーは未使用**: 本評価は repo の `seal` split に対する **harness 直接評価**（guard 開封トークン経路は通していない）。科学的内容（汚染ゼロ held-out の項目別対比）は等価。厳密な F-013 ceremony を要するなら別途 `docs/SEALED_EVAL_RUNBOOK.md` の guard 経路で再実行可。
- supreme の非学習層（mode/relation/role/risk/t1/quality の規則部）は v021_core で人手調整された出発係数のまま＝seal に対しては out-of-distribution。これは**より厳しい（正直な）**テスト。

## 結論

**真値 = 「総合ほぼ同点・項目別で quality/scene/mode 勝ち、relation/t3 負け、role 回帰」。** プロジェクトの成功目標（弱5全↑∧強維持）は現状未達。改善の優先は (1) role 回帰の是正、(2) relation 規則の封印分布での再検討、(3) t3 は mode 上限が構造的天井（研究者領分）。
