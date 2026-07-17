# F-013 封印評価（真値・改善後）— supreme2 vs baseline / coverage_v1 seal

> **⚠️ 撤回注記（2026-06-26・ADR 0049）**: 本レポートの結論（**0.6305 vs 0.4782「大きく上回る」・弱5 WIN4・
> 強3全 maintained・risk 0.52→0.94**）のうち rule_derived 6層（risk_tier/t1_state/t2_mode/t2_role/t2_relation/
> quality_regime）に依存する部分は**能力主張として撤回済み**。特に risk の +0.41 は GT 生成規則（純TTC）への
> 整合＝写しであり能力ではない。これらは仕様適合（spec-conformance）の回帰値としてのみ有効。能力を語れるのは
> intent 層（scene=WIN +0.049 / t3=LOSE −0.078）のみ。詳細: `decisions/0049-evaluation-contamination-retraction.md`。

- 実施: 2026-06-24（ADR 0030 の3修正後の再確認）。前回 = `sealeval-coverage_v1-seal-20260623.md`（改善前）。
- データ/指標/方法: 2026-06-23 と同一（`N04-scenario-contract@main 2f3da56` coverage_v1・fit=train406 / 評価=seal86・lineage-disjoint・8層 global acc・δ_strong=0.02・harness 直接評価）。
- 規律: 修正は **train で開発・eval(172・未使用 held-out)で検証**。**seal は合わせ込みに一切使わない**（最終確認のみ）。全800テスト緑。

## 真値（改善後・seal 86件）

| 層 | 種別 | baseline | supreme2 | Δ(sup−bas) | verdict | 改善前Δ |
|---|---|---:|---:|---:|---|---:|
| risk_tier      | 強 | 0.5245 | 0.9387 | +0.4142 | maintained | +0.0000 |
| t1_state       | 強 | 0.5490 | 0.5490 | +0.0000 | maintained | +0.0000 |
| t2_role        | 強 | 0.5711 | 0.6446 | +0.0735 | maintained | −0.0760 |
| t2_mode        | 弱 | 0.1765 | 0.4730 | +0.2966 | **WIN** | +0.0245 |
| t2_relation    | 弱 | 0.5392 | 0.6029 | +0.0637 | **WIN** | −0.1422 |
| t3_hypothesis  | 弱 | 0.5956 | 0.5172 | −0.0784 | LOSE | −0.2451 |
| quality_regime | 弱 | 0.4020 | 0.8015 | +0.3995 | WIN | +0.3995 |
| scene_regime   | 弱 | 0.4681 | 0.5172 | +0.0490 | WIN | +0.0490 |
| **8層平均**    |    | **0.4782** | **0.6305** | **+0.1523** | | +0.0012 |

- **総合: 実質タイ（0.4795）→ 0.5702 → 0.6305（baseline を +0.152 で大きく上回る）。**
- 弱5＝**WIN4**(mode +0.30/relation/quality/scene)・LOSE1(t3 −0.078)。強3＝**全 maintained**（risk +0.41・role +0.074）。
- risk_tier を純 TTC へ整合（ADR 0033）で risk 0.52→0.94・連動で mode 0.31→0.47。副作用で t3 が draw→LOSE（会話中の衝突危険フレームが正しく emergency mode 化し intent 復元不可＝既知天井）。

## 修正（ADR 0030/0031/0032/0033・held-out 駆動）

1. **role**: tie-break を緊急音優先（`source_alarm` を `source_speech` より先）。`has_alarm ∧ 発話リンク`同点を speech に誤決していた回帰（62件全て supreme のみ誤り）を解消。
2. **relation**: `call_user` を `{"call_user":true}` キーで検出（旧 `type=="call_user"` は常に False）。addressing_user 168件の grouped 誤落を解消。
3. **mode**: `conv_request` を `call_user ∧ ¬conv_strong ∧ ¬危険` でゲート補完。
4. **mode/t3（ADR 0031）**: conv_request の caution 除外が過剰だった。caution では会話要求を alert_required より優先（baseline 忠実）。t3 の `conv_participating→alert_required` 88件を解消。
5. **t3（ADR 0032・train-CV 駆動）**: traffic_unstable を学習層が never 出せず 0.000 だった。規則層で `forward_caution 比率>0.2 → traffic_unstable`（baseline 忠実）。train 内 5-fold CV で開発・eval/seal で確認。
6. **risk_tier（ADR 0033・GT 整合）**: coverage_v1 の risk GT は kind 非依存の純 TTC ルール（ttc≤2→danger/≤12→caution）。モデルの kind 別閾値（alarm=5 等）と系統的にズレ 0.52 だった。t0 を全 kind (12,2) に統一。**risk 0.52→0.94（+0.41）・連動で mode 0.31→0.47**。supreme のみ（baseline は read-only で不変）。t0 テスト7件を新契約へ更新。

6件とも **coverage_v1 が露出させた実装欠陥/GT 不整合**（v021_core では空クラス・偏り・kind 別閾値で隠れていた）であり、汚染由来の過適合ではない。held-out（eval / train-CV）で汎化を確認済み。

## 既知の限界（受容）

- **t3 LOSE（−0.078）**: risk を純 TTC で正しく danger 化した副作用。会話エピソード中の衝突危険フレーム（GT t3=conv_participating ∧ risk=danger=380件）が正しく mode=emergency になり、t3 が会話 intent を mode 窓から復元できず sustained_alert に落ちる。intent_derived GT の mode→t3 ボトルネック（heuristic_confirmed 61% 近傍が原理 ceiling）＝research 領分。intent ラベルへの t3 合わせ込みはしない。env_start/uncertain_context/hazard_declining（~419 frames）も同様に 0.000 のまま（分離信号なし）。
- **t1_state 未整合（0.55）**: GT t1≈軌跡 dynamics 由来で単一 clean 信号なし。idle→approach 163件は静的 approach 閾値 vs 軌跡の不一致だが、合わせるには dynamics 検出再設計（合成軌跡への過適合）が要るため触らない。
- **risk 純 TTC は coverage_v1 GT レシピへの整合**でもある（閾値 2/12 はこのコーパス由来）。実世界 risk の kind 依存性は別問題＝新 held-out / 実データで再検証すべき。
- `side_rear_caution`/`uncertain` mode 未補完（証拠曖昧・過適合リスク）。
- 統計的有意性なし（U11・86件点推定）。合成データ（U13）。
- seal は本評価で2回参照（baseline 比較×改善後確認）したが、いずれも**学習・調整には未使用**（develop=train/eval の規律維持）。
