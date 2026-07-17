# ADR 0039: v1.5 — 低 QoS → uncertain mode(欠落クラス回収)

- 日付: 2026-06-24 / ステータス: 採用 / 関連: F-007(mode)・契約 v1.5(C-1b)。
- エビデンス: coverage_v2(v1.5) eval/seal・全823+テスト緑。

## 背景・決定
mode の uncertain は supreme が出せない欠落クラス。coverage_v2/train で uncertain の QoS≈0.39(最低・他クラス ≥0.61)。
core の mode 結線直後に presence-gated 上書き: `_episode 在 ∧ QoS < 0.5 → t2_mode="uncertain"`。
ヒステリシス状態(prev_mode)は raw のまま。episode 不在(v1.4)は不変=後方互換。

## 結果(eval)
- mode 0.467(v1.4・不変) → **0.504(v1.5・+0.037)**。8層平均 0.6309 → **0.7565**。seal: mode 0.507・8層 0.7540。

## 限界(正直に・mode の天井)
- 回収できたのは uncertain のみ。**conv_ongoing/conv_request は同じ call_user+speech で曖昧**(分離不能)、
  **side_rear_caution は観測署名なし**(theta>90 で 0%)。これらは ambiguity 天井で、規則化は過適合のため不追求。
- これ以上の mode 向上は契約 v1.6 の新観測信号(会話状態の細分・背面方位の明示)か実データが要る。
