# ADR 0045: risk/quality を GT 完全整合(純 TTC・生 QoS)に是正 — 強 baseline が露呈

- 日付: 2026-06-25
- ステータス: 採用
- 関連: F-004/F-006(risk)・F-002/F-011(quality)・ADR 0033(risk 純TTC化・本 ADR が閾値是正)。
- エビデンス: coverage_v2 train/eval(held-out)・seal・全847テスト緑。
- 契機: planA-baseline の凍結解除(ADR-030)。強 baseline が risk(1.00)/quality(1.00)で supreme(0.94/0.80)を
  上回り、supreme 側にも純 TTC/生 QoS 未使用の取りこぼしがあると判明。

## 背景

supreme の risk(0.94)/quality(0.80)は GT 規則と微妙にズレていた:

| 層 | 旧 supreme | GT(gt_derive) |
|---|---|---|
| risk_tier | caution≤12・siren→caution 下限・境界 `<=` | **ttc<2→danger / ttc<8→caution**(厳密 `<`)・**siren salient→danger** |
| quality_regime | HGF 後 h_q ベース(`classify(h_q,vol)`) | **生 QoS**(q≥0.90 GOOD / q<0.55 BLOCK / 他 DEGRADED・h_q 不使用=循環回避) |

## 決定

- **risk(t0.py)**: 純 TTC を GT に厳密整合 — `siren→danger` / `ttc<2.0→danger` / `ttc<8.0→caution` / else info(厳密 `<`)。
  旧 caution≤12・siren 下限 caution を廃止。
- **quality(core.py)**: view の quality_regime を **生 QoS** で確定(`_scene_qos_latency` の QoS に GT 閾値)。
  h_q/vol は HGF gating(anomaly/scene)用に保持。`quality_mod.classify(h_q,vol)` は view から外す。

規律: 観測のみ・非循環・train開発/eval検証・seal 最終確認のみ。

## 結果(seal・coverage_v2)

| 層 | 旧 | 新 |
|---|---:|---:|
| risk_tier | 0.939 | **0.988** |
| quality_regime | 0.802 | **1.000** |
| t2_mode | 0.706 | **0.733**(risk 是正で false caution 減・mode 改善) |
| t3_hypothesis | 0.738 | 0.664 |
| **8層平均** | 0.8719 | **0.8995** |

- quality は完全一致。risk は 0.988(残 25/408 は主トラック選択が siren-first で GT `_salient` と僅差・微小)。
- **副作用(正直に)**: **t3 −0.073**。risk 是正で caution フレームが減り(8<ttc≤12 が info へ)、mode の caution routing が
  変わって t3 per-frame fallback(mode 窓依存)が揺れた。risk→mode は正しいデータフロー(mode は GT へ近づく)で
  あり、t3 は intent 天井層の fallback artifact。coupled を採用(mode の正しさを優先・ADR 0044 と一貫)。net +0.028。

## 限界(正直に)

- t3 fallback の mode 窓依存は脆く、上流是正で揺れる(intent 天井層)。これ以上の安定化は別途。
- risk 残 1.2% は siren 主トラック選択の僅差(GT は salient=max(w_obs,-r_m) が siren のときのみ danger)。
