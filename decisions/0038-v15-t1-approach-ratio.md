# ADR 0038: v1.5 — episode.approach_ratio で t1_state を補正（relation も連動改善）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-006(t1)・F-008(relation)・契約 v1.5(C-1a)・`docs/PLAN-v1.5-input-support.md`。
- エビデンス: coverage_v2(v1.5) eval/seal・全819+テスト緑。

## 背景

t1_state は両実装で 0.55。現 t1 の「ttc<12 → approach」は**静止近接物も approach にする**（idle/depart→approach の
誤り。t1 は軌跡 dynamics 由来）。v1.5 の `episode.approach_ratio`（実際に距離が減ったフレーム割合）は実接近を直接示す。

coverage_v2/train の t1 別 approach_ratio: **approach 0.54 / idle 0.07 / depart 0.08 / pass 0.40** で分離。

## 決定

`core` の t1 結線直後に presence-gated 補正:
- `approach_ratio >= 0.3` → **approach**（実接近）。
- 偽 approach（現 t1=approach だが approach_ratio<0.3）→ `hazard_trend > 0.005`(離反)なら **depart**、他は **idle**。
- それ以外は現 t1 維持。t1 状態機(prev_t1)は raw のまま不変（出力ラベルのみ補正）。episode 不在(v1.4)は不変=後方互換。

補正後の `approaching` が relation/mode forward_caution に波及（より正確な接近 → relation 改善）。

## 結果（eval・coverage_v1 vs coverage_v2）

| | v1.4 | v1.5 |
|---|---:|---:|
| t1_state | 0.556 | **0.606（+0.05）** |
| t2_relation | 0.596 | **0.663（+0.067・連動）** |
| 8層平均 | 0.6309 | **0.7519** |

- **seal: 8層平均 0.7497**（t1 0.598・relation 0.659）。v1.4 完全不変・全テスト緑＋t1 v1.5 テスト4件。
- t1 の approach 取り違えを実接近信号で是正し、relation の approaching 検出も同時に改善（`approaching` 連動）。

## 限界（正直に）

- t1 は **idle/depart/pass の分離が残る**（approach_ratio は approach を主に分離。pass は approach_ratio mid で approach に
  寄る・少数）。これ以上は軌跡の細かい弁別で、合わせ込みは過適合のため不追求。
