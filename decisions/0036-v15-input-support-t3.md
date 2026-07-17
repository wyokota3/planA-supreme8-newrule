# ADR 0036: v1.5 入力対応 — T-T3（episode.speech_ratio → conv_participating）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-009(t3)・契約 v1.5(C-1a)・ADR 0033(conv-during-danger 副作用)・0034/0035(v1.5)・`docs/PLAN-v1.5-input-support.md`。
- エビデンス: coverage_v2(v1.5) vs coverage_v1(v1.4) eval・全813+テスト緑。

## 背景

ADR 0033 で risk を純 TTC で正しく danger 化したところ、**会話エピソード中の衝突危険フレーム**
（GT t3=conv_participating ∧ risk=danger → mode=emergency）で t3 が会話 intent を mode 窓から復元できず
sustained_alert に落ちた（t3 −0.078 LOSE の主因）。t3 は intent_derived で mode→t3 経路がボトルネック。

coverage_v2/train の診断: **conv_participating の `episode.speech_ratio` ≈ 0.98**（突出）、他クラスは ≤0.5。
また t3 はほぼシナリオ内一定（402/4）。

## 決定

`core._run_one_scenario` の t3 結線直後に **presence-gated 上書き**: `episode.speech_ratio >= 0.7` なら
`t3_hypothesis = conv_participating`（`core.py` `_T3_V15_SPEECH=0.7`）。speech_ratio が高いのは
conv_participating のみ（他クラス ≤0.5）なので他層を侵さない。mode=emergency でも会話 intent を観測から保持し
ADR 0033 の副作用を解消。episode 不在(v1.4)は不変=後方互換。

## 結果（eval・coverage_v1 vs coverage_v2）

| | coverage_v1 (v1.4) | coverage_v2 (v1.5) |
|---|---:|---:|
| t3_hypothesis | 0.52（不変） | **0.61（+0.09）** |
| 8層平均 | 0.6309 | **0.7283** |

- 会話×衝突危険の conv_participating を復元（ADR 0033 副作用解消）。**v1.4 完全不変**＝後方互換（seal 0.6305 保持）。
- 全テスト緑＋t3 v1.5 テスト3件。

## v1.5 入力対応の完了（Phase 0 + T-Role + T-Scene + T-T3）

| 層 | v1.4 | v1.5(coverage_v2/eval) |
|---|---:|---:|
| t2_role | 0.63 | **0.96**（ADR 0034） |
| scene_regime | 0.53 | **0.89**（ADR 0035） |
| t3_hypothesis | 0.52 | **0.61**（本 ADR） |
| **8層平均** | **0.631** | **0.728（+0.097）** |

すべて後方互換ゲートで v1.4（coverage_v1/seal 0.6305）を不変に保持。

## 限界・次

- t3 の残り（env_start/uncertain_context/hazard_declining 等）は speech_ratio 以外の episode 信号や mode 表現力が
  要る（heuristic_confirmed 61% 近傍）。これ以上の合わせ込みは過適合のため不追求。
- 検証は coverage_v2/eval（controlled A/B）。**最終確認は新 seed の seal が望ましい**（同一 seal 多重検定回避）。
- 実運用前に: 正規 v1.5 採番・coverage_v2 の必須 emit・新 seal での最終測定。
