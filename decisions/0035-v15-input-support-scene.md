# ADR 0035: v1.5 入力対応 — T-Scene（episode 集約 stability → scene_regime）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-010(scene)・契約 v1.5(C-1b)・ADR 0034(v1.5 Phase0/T-Role)・`docs/PLAN-v1.5-input-support.md`。
- エビデンス: coverage_v2(v1.5) vs coverage_v1(v1.4) eval・全807+テスト緑。

## 背景

scene_regime は両実装で 0.47〜0.52（天井 heuristic_confirmed 77%）。v1.5 の `scene_state.stability`
（qos_trend / track_churn / change_point）で場面の長期健全性を観測できる。

**重要な発見**: coverage の **scene_regime は 1 シナリオ内で完全に一定（406/406）= episode-level intent**。
per-frame の stability 上書きを試すと、CHANGING シナリオの早期（高 QoS・平坦）フレームを STABLE と誤り
CHANGING が 0.92→0.43 に**回帰**した（per-frame と episode-level intent の粒度不一致）。

## 決定

**episode 集約**で 1 シナリオ = 1 regime に分類し全フレームへ適用（presence-gated・`core._scene_regime_sequence`）:
- `min(qos_trend) > -0.1`（降下なし）→ **STABLE**
- 降下あり ∧ `mean(QoS) < 0.5`（平均 QoS 低・settled low）→ **DEGRADING**
- 降下あり ∧ `mean(QoS) >= 0.5`（中 QoS・遷移）→ **CHANGING**

閾値は coverage_v2/train の regime 別平均（DEGRADING QoS0.44/qos_trend-0.39 / CHANGING 0.63/-0.27 /
STABLE 0.88/0.00）で分離。stability 不在(v1.4)は従来の学習 HGF 経路のまま=後方互換。

## 結果（eval・coverage_v1 vs coverage_v2）

| | coverage_v1 (v1.4) | coverage_v2 (v1.5) |
|---|---:|---:|
| scene acc | 0.5307（不変） | **0.8924（+0.362）** |
| STABLE | 0.61 | **1.00** |
| CHANGING | 0.92 | **0.96** |
| DEGRADING | 0.00 | **0.64** |
| 8層平均 | 0.6309 | **0.7171** |

- **3 クラスすべて改善**（DEGRADING 0→0.64・STABLE 0.61→1.00・CHANGING 維持）。heuristic_confirmed 77%
  を超える（77% は独立判定の一致率であり達成可能 acc の下限ではない）。
- **v1.4（coverage_v1）は完全不変**＝後方互換（seal 0.6305 保持）。全テスト緑＋scene v1.5 テスト6件追加。

## 限界・次

- DEGRADING 0.64（一部 DEGRADING が CHANGING へ）。閾値 0.5 は原理的代表値で、これ以上の合わせ込みは過適合の
  ため不追求。
- 検証は coverage_v2/eval（controlled A/B）。seal 最終は新 seal が望ましい。
- 次: **T-T3**（episode→会話×衝突危険の conv_participating 復元・ADR 0033 副作用解消）。
