# ADR 0030: held-out 駆動の role/relation/mode 修正（封印再計測の3欠陥）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-006(role)・F-008(relation)・F-007(mode)・F-013(封印評価)。ADR 0017/0016/0015/0028 を一部上書き。
- エビデンス: `reports/sealeval-coverage_v1-seal-20260624-improved.md`（seal 真値）・eval held-out 検証。

## 背景

2026-06-23 の封印再計測（`reports/sealeval-coverage_v1-seal-20260623.md`）で、coverage_v1/seal（balanced・汚染ゼロ）の真値は **supreme 0.4795 ≈ baseline 0.4782（実質タイ）**、role が DEGRADED・relation/t3 が LOSE だった。in-sample/CV の楽観は held-out で消えていた。

原因を **train で開発・eval(未使用 held-out)で検証**（seal は最後の確認のみ・合わせ込み禁止）した結果、3つは**汚染由来の過適合ではなく、coverage_v1 が露出させた実装欠陥**と判明。いずれも v021_core（空クラス・偏り）では発火しなかったため見逃されていた。

## 決定

### 1. role tie-break を緊急音優先に（`role.py` `_LABEL_ORDER`）
`has_alarm ∧ linked_speech_score>0.4 ∧ speech track 無し`のとき `source_alarm(1.5)` と `source_speech(1.5)` が同点。旧 `_LABEL_ORDER` は speech 先頭で speech を誤選択。baseline は posterior 順序で source_alarm を選ぶ（緊急音優先・実測）。`_LABEL_ORDER` を `(alarm, vehicle, speech, human, object, unknown)` に変更。
→ seal role **−0.076(DEGRADED) → +0.074(maintained)**。disagree 62件全て supreme のみ誤りだった回帰を解消。ADR 0028 の role 改変は held-out で裏目だった点を本 ADR が上書き。

### 2. relation の call_user 取りこぼし修正（`core.py` `_relation_evidence`）
utter_event は `{"call_user": true}` 形式（`type` キー無し）。旧実装 `e.get("type")=="call_user"` は常に False＝addressing_user が一切発火せず grouped 既定へ誤落。baseline t2.py L254 `any(bool(u.get("call_user")) ...)` に忠実化。
→ seal relation **−0.142(LOSE) → +0.064(WIN)**。addressing_user 168件の誤落を解消。

### 3. mode に conv_request を補完（`core.py` `_mode_logits`）
`conv_request`/`side_rear_caution`/`uncertain` は発火規則が無く必ず誤り（v021_core では 0例）。coverage_v1 で conv_request GT は全て call_user を伴う。決定2で修正した call_user を使い、**強信号と競合しない形でゲート**: `call_user ∧ ¬conv_strong ∧ risk∉{danger,caution} → conv_request(4.0)`。emergency(danger)/conv_ongoing(conv_strong) は優先され誤奪取しない。
→ seal mode **+0.025 → +0.135(WIN)**。連動で t3 **−0.245 → −0.172**（mode→t3 経路）。

## 結果（seal 真値・86件）

8層平均 **baseline 0.4782 / supreme 0.5469（+0.069）**。弱5＝WIN4(mode/relation/quality/scene)・LOSE1(t3)、強3＝全 maintained（role は +0.074 で baseline 超）。**実質タイ→明確超え**に転換。全800テスト緑。

## 残件・限界

- **t3 は依然 LOSE(−0.172)**: mode→t3 の構造天井。mode 改善で縮小したが、baseline 手作り t3(0.596) を学習(0.424) が超えるには mode のさらなる作り込み（research 領分）。**seal 合わせ込みはしない**。
- `side_rear_caution`/`uncertain` mode は未補完（証拠が曖昧で過適合リスク）。
- 統計的有意性なし（U11・86件点推定）。合成データ（U13）。
- 検証は eval held-out（train と lineage-disjoint）。seal は最終確認のみで開発に未使用。
