# ADR 0028: t2_role 忠実度ギャップ修正 — object-vehicle 経路の忠実再現

- 日付: 2026-06-15
- ステータス: 採用（監査 pass・`reports/audit-20260615-0242-role-B.md`）
- 関連: ADR 0017（F-006 強い項目の独立再実装）、`reports/role-diagnose-20260615-0233.md`（診断）、
  baseline `external-data/planA-baseline/src/ns_epi/t2.py` L187-192（spec §3.5）

## 背景

旧 supreme（l04-ours）との比較で、強項目 t2_role が新 supreme **0.8714** vs 旧 **0.9333**（−0.062）と
劣後していた。診断で **(B) 忠実度ギャップ**と確定: 新 supreme `core._role_evidence` の `has_vehicle` が
`audio track の vehicle` のみを見ており、baseline の恒久規則 **`has_vehicle = audio ∨ object track`**
（spec §3.5・baseline t2.py L187-192）の **object-vehicle 経路を再現漏れ**していた。vehicle が object track
で表されるフレーム（ns017_vehicle_lifecycle 等）で **source_vehicle → unknown が18件**潰れていた
（誤り27件の67%・系統的）。

## 決定

`core._role_evidence` の `has_vehicle` を `_has_vehicle_evidence(snap) = audio_vehicle ∨ object_vehicle`
へ修正（baseline spec §3.5 の忠実再現）。ヘルパ `_has_object_type` / `_has_vehicle_evidence` を追加。
**`role.py` の logit 規則 r1–r5（閾値・優先順）は無改変**。EMA/温度平滑は導入しない（ADR 0017:
softmax/EMA は上流共有基盤＝role スコープ外）。

## 過適合でない根拠（忠実再現・監査確認）

- 変更は `type=="vehicle"` の**構造述語のみ**で、ts/scenario_id/特定フレーム依存の分岐を持たない
  （v021_core 合わせ込みでない）。baseline が spec §3.5 で恒久定義した規則の再現。
- **偽陽性ゼロ**: role acc 0.8714→0.9571 は取りこぼし18件回復ちょうど（+18）で、GT≠vehicle を
  vehicle に誤予測した過剰予測は0件（混同行列確認）。`role.py` の `elif has_vehicle`（alarm 優先）
  により siren 共在は source_alarm 維持。

## 影響

- t2_role: 0.8714 → **0.9571**（旧 supreme 0.9333 を **+0.024 上回る**）。他7層は dev-eval で完全不変。
- 回帰テスト `tests/test_role_object_vehicle.py`（5件）追加で object-vehicle 経路・偽陽性ガード・
  過剰予測なし・決定性を end-to-end で pin（監査の回帰テスト欠如指摘を解消）。795テスト全緑。
- 残差9件（誤り27→9）のうち5件は alarm 優先 elif の硬さ・GT 僅差で、EMA/温度（ADR 0017 上流スコープ外）
  の領域＝本修正の対象外。
- すべて in-sample（v021_core）値。最終確定は封印（F-013）。
