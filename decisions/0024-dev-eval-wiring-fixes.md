# ADR 0024: 開発セット評価で露見した結線バグの修正 + tuning ループの方法論的限界

- 日付: 2026-06-14
- ステータス: 採用（ユーザー承認済み・2026-06-14）
- 関連: ADR 0023（F-013）、ADR 0022（core ランナー）、ADR 0020（F-009 t3）、ADR 0019（F-010 scene HGF）、
  ADR 0014（F-011 quality 再較正・vol=sigma1 計測）、ADR 0006（v1.4 語彙）、ADR 0012（指標式）、
  `scripts/run_dev_eval.py` / `scripts/run_dev_eval_diagnose.py`、`reports/dev-eval-*.md`

## 背景

F-013 完了後、研究者領分の本番封印 verdict に先立ち、**開発セット（v021_core）での in-sample 評価**を
`scripts/run_dev_eval.py` で実施した（新 supreme `core.run_supreme` を v021_core 実 PSO 入力で実走 →
`harness` 採点 → 研究者再計測済み v1.4 baseline と項目別対比。GT は ADR 0006 の v1.3→v1.4 正準化を適用）。

結果、新 supreme は弱5項目のうち **t3_hypothesis / scene_regime / quality_regime の3つで baseline に
大きく負けた**（t3 0.329 / scene 0.324 / quality 0.476）。`scripts/run_dev_eval_diagnose.py` の混同行列・
語彙被覆分析で、これらは「未チューニング係数」ではなく **core.py の結線が出力語彙を潰す構造バグ**と判明した。

## 診断（構造バグ vs 較正の切り分け）

- **scene_regime**: CHANGING を97%出力＝ほぼ定数、GT 最多の STABLE（54%）を一度も出さない。
  真因＝`_scene_regime_sequence` が `fit([])` で grid 最緩閾値に潰れ、かつ persistence の nominal=0.5 が
  health 信号の動作点（≈0.93）と不整合で、平坦健全列でも逸脱が蓄積し CHANGING へ倒れていた。
- **t3_hypothesis**: 10クラス中3クラス（conv/traffic/quiet）しか出さず、7クラスを一度も出さない。
  真因＝SPEC F-009 / ADR 0020 が要求する「非学習7クラスの baseline 規則踏襲」が**未配線**
  （`classify_t3` は3境界ロジスティックのみ。HANDOVER §7「classify_t3 未配線」が示唆）。
- **quality_regime**: GOOD→DEGRADED を98/154＝1段悲観バイアス。真因＝**層の取り違え**。
  `core._hq_vol_sequences` が quality の `vol` に scene 用 `exp(μ2)`（HGF 層2 log-volatility）を渡していたが、
  GOOD ゲート `vol<0.01` は `1/π1`（層1事後分散＝sigma1）を想定（ADR 0014 L19: vol は全210で
  0.0058〜0.0099・常に <0.01）。誤った量（最大0.0585）で正当な GOOD 55件が spurious に DEGRADED へ。

## 決定（修正・すべて構造的/正準値・過適合なし）

1. **scene 結線（core.py）**: persistence nominal = 信号系列の**中央値**（頑健ベースライン推定）、
   分類閾値 = **F-010 classify 契約テストの正準代表値**。v021_core への合わせ込みなし。
2. **t3 hypothesis（t3.py）**: `_rule_hypothesis` を新設し、**baseline `_classify_t3` の構造条件・閾値・
   優先順を逐語踏襲**（mode 窓6＝baseline 値）。`step` は規則発火→採用 / 未発火→既存ロジスティック委譲。
   in-sample で +0.005 だった窓64は**過適合回避で不採用**。`classify_t3`/集約特徴は不変。
3. **quality 結線（core.py / scene.py）**: `HgfTrajectory.var1`（=1/π1）を追加し、`_hq_vol_sequences` の
   `vol` を `var1` へ結線。scene の `volatility`（exp μ2）の意味は不変（scene 非悪化）。`quality.py` 不変。
4. **mode 結線（core.py）**: `_mode_logits` が v1.4 mode 10クラス中6クラスにしか logit 経路を持たず
   `surround_activity` 等が到達不能だった構造バグを修正。群衆（`n_humans>=3` ∧ conv_strong でない）に
   surround_activity の logit を結線（**偽陽性ゼロの構造分離**・閾値合わせ込みでない）。`uncertain`/
   `conv_request` は証拠重複で mode acc を下げる過適合リスク / GT 非出現のため**意図的に未結線**。
   これにより t3 規則層の `crowd_tendency` も発火可能になった（上流証拠の供給）。

**テスト更新**（test-writer）: `test_Fbase001_1_state_carryover_changes_output_vs_single_frame` を、
バグ依存の定常会話 fixture（single≠tail が quality flip バグ由来だった）から、**t1 の接近→発散遷移**
fixture へ更新（single=approach ≠ tail=pass を t1 の前史依存で正しく成立）。意図（状態持ち越しの検出）は頑健化。

## 結果（すべて in-sample = v021_core 開発セット・封印 verdict ではない）

| 層 | before | after | baseline v1.4 | verdict |
| --- | ---: | ---: | ---: | --- |
| t2_mode | 0.581 | **0.624** | 0.571 | **win**（draw→win 反転） |
| scene_regime | 0.324 | **0.452** | 0.543 | lose（改善） |
| t3_hypothesis | 0.329 | **0.357** | 0.629 | lose（語彙3→8回復・改善） |
| quality_regime | 0.476 | **0.724** | 0.667 | **win**（反転） |

弱5: win1/draw1/lose3（avg 0.510）→ **win3/lose2（avg 0.599）**。強3は全 maintained で不変。
（t2_relation は元から win 0.838。残る lose は t3_hypothesis と scene_regime。）
全740テスト緑・他層完全非悪化・決定的。`success_goal` は False（t3/scene の lose 残）。

## 方法論的限界・申し送り

- **残る t3/scene の lose は in-sample では原理的にこれ以上直せない**:
  - t3 の未出力クラスのうち `crowd_tendency` は決定4（mode surround_activity 結線）で発火可能になった。
    残る `hazard_declining` / `uncertain_context` は別調査で**(B) 構造バグでないと確定**:
    - `uncertain_context`: 上流 `uncertain` の結線は conv/env_change と証拠が重なり mode acc を下げる
      **過適合リスク**のため見送り（decision4）。
    - `hazard_declining`: baseline 自体が **PENDING**（danger 源未定義・`external-data/planA-baseline` ADR-006 決定2）で
      忠実再現すべき規則が無い。必要な証拠は **danger の時系列スロープ**で t3 入力に存在しない
      （ADR 0020 決定4 のスコープ外）。argmax mode から GT 2フレームを切り出すと alert_required を誤射
      （過適合）。扱うには F-009 のスコープ拡張（danger 信号の t3 結線・新 ADR）が要るが payoff は
      最大 +0.0095 で過大。**直さないのが正しい**（コード無改変で確認）。
    いずれも in-sample では原理的に直せない。**これで全 lose 層の原因調査は完了**（構造修正の鉱脈を掘り尽くした）。
  - t3/scene の境界較正（閾値・感度）の微調整は **held-out 封印での fit 実験が前提**。
    **in-sample（v021_core）で最大化すると過適合＝封印の意味を壊す**ため本ループでは触らない。
- **全数値は in-sample**（v021_core は F-005 エラー分析＝改良の開発に使用済み）。**封印 verdict ではない**。
  最終判定は held-out 人手封印が前提（`docs/SEALED_EVAL_RUNBOOK.md` / F-013）。
- **検証ギャップ（重要）**: 各機能監査（F-009/F-010/F-011）は fixture 上の**機構**は通したが、
  **実データでの全出力語彙の被覆**を検証していなかった。end-to-end の dev_eval が初めて露見させた。
  今後の監査・テストは「全出力語彙が実データ経路で到達可能か（定数潰れ・語彙欠落が無いか）」も見るべき。

## 影響

- 修正は core.py（scene/quality 結線）・t3.py（規則層）・scene.py（var1 追加）に限定。3機能（F-009/F-010/
  F-基盤-001）の挙動を改善する FIXING_DEVIATIONS。テストは1件を遷移 fixture へ更新（頑健化）。
- 受け入れ条件・公開契約は不変（全740テスト緑）。`scripts/run_dev_eval.py` / `run_dev_eval_diagnose.py` は
  分析ランナー（SPEC 機能ではない）。
