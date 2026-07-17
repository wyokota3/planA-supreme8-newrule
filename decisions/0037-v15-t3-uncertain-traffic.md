# ADR 0037: v1.5 T-T3 拡張 — uncertain_context(低 QoS)/ traffic_unstable(接近)を episode 集約で回収

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-009(t3)・契約 v1.5(C-1a/b)・ADR 0036(T-T3 conv_participating)・`docs/PLAN-v1.5-input-support.md`。
- エビデンス: coverage_v2(v1.5) eval/seal・全816+テスト緑。

## 背景

ADR 0036 で conv_participating を回収後、t3 は 0.61。**まだ 0.000 の4クラス**（env_start/uncertain_context/
traffic_unstable/hazard_declining）が残った。coverage_v2/train の t3 別観測署名:

| t3(0.000) | approach | qos_trend | **QoS** | hazard | 分離信号 |
|---|---:|---:|---:|---:|---|
| uncertain_context | 0.06 | −0.15 | **0.351(最低)** | 0 | 低 QoS(観測劣化) |
| traffic_unstable | **0.708(最高)** | −0.30 | 0.46 | 0 | 高 approach |
| env_start | 0.53 | −0.33 | 0.61 | 0 | 他と重なる(不採用) |
| hazard_declining | 0.00 | −0.59 | 0.72 | +0.07 | 小・微弱(不採用) |

## 決定

`core._t3_v15_episode_override(snaps)`(episode 集約・t3 はシナリオ内ほぼ一定)で優先順に分類:
1. `mean(speech_ratio) >= 0.7` → conv_participating（ADR 0036）。
2. `mean(QoS) < 0.4` → **uncertain_context**（観測劣化=文脈断定不能・素直な意味）。
3. `mean(approach_ratio) >= 0.65` → **traffic_unstable**（接近継続=交通不安定）。
4. 該当なし → per-frame t3 のまま。

**env_start/hazard_declining は他クラスと信号が重なる/小さく、規則化は過適合のため写さない**（heuristic 天井・research 領分）。episode 不在(v1.4)は不変=後方互換。

## 結果（eval・coverage_v1 vs coverage_v2）

| | v1.4 | v1.5 | per-class(v1.5) |
|---|---:|---:|---|
| t3_hypothesis | 0.5201 | **0.6832** | uncertain 0→0.68・traffic 0→0.50・conv 0.97 維持 |
| 8層平均 | 0.6309 | **0.7374** | — |

- **seal 最終: t3 0.6789・8層平均 0.7368**（coverage_v2/seal 86件）。
- v1.4 完全不変・全テスト緑＋t3 v1.5 テスト3件追加。

## 限界（正直に）

- **sustained_alert が 0.56→0.35 に巻き込まれ**（一部 sustained シナリオの mean approach が 0.65 超で traffic へ）。
  uncertain(79)+traffic(64) の回収が上回り t3 は純増（+0.16 over v1.4）だが、approach 信号が sustained/traffic で
  重なる残差。これ以上の閾値合わせ込みは過適合のため不追求。
- env_start/hazard_declining は依然 0.000（分離信号なし＝原理天井）。

## v1.5 入力対応 全体（最終）

| 層 | v1.4 | v1.5(seal) |
|---|---:|---:|
| t2_role | 0.63 | **0.96** |
| scene_regime | 0.53 | **0.89** |
| t3_hypothesis | 0.52 | **0.68** |
| **8層平均** | **0.631** | **0.737** |

ADR 0034-0037・後方互換ゲートで v1.4(seal 0.6305)不変。
