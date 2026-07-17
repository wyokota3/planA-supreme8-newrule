# ADR 0031: conv_request を caution で alert_required より優先（t3 conv_participating 回復）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-007(mode)・F-009(t3)。ADR 0030 の conv_request ゲートを精緻化。
- エビデンス: `reports/sealeval-coverage_v1-seal-20260624-improved.md`（更新）・eval held-out。

## 背景

ADR 0030 で `conv_request` を `call_user ∧ ¬conv_strong ∧ risk∉{danger,caution}` でゲートした。
この **caution 除外が過剰**で、t3 の最大混同 `conv_participating → alert_required`（eval 88件）の原因だった。

機序（eval 88件で確定）: GT risk=danger・GT t3=conv_participating のフレームで、モデルは risk を
caution と誤判定 → mode 規則が `caution → alert_required` を立てる（conv_request は caution 除外で不発）
→ t3 規則層が `alert_ratio>0.25` で `alert_required` を学習 conv 経路より先に確定。
**baseline は同フレームで mode=conv_request（call_user 優先）→ t3=conv_participating** と正答していた。

## 決定

`_mode_logits` を再構成し、**caution では会話要求(conv_request)を alert_required より優先**:
- `conv_request_fires = call_user ∧ ¬conv_strong ∧ risk≠DANGER`
- `risk==CAUTION ∧ ¬conv_request_fires` のときのみ `alert_required` を立てる（相互排他）。
- `risk==DANGER` は従来どおり emergency 優先（conv_request は不発）。

baseline F-007-8（call_user→conv_request は危険でなければ alert より文脈支配的）への忠実化であり、
seal 合わせ込みではない（eval held-out で汎化確認）。

## 結果（seal 真値・86件）

| 層 | ADR 0030 後 | 本 ADR 後 |
|---|---:|---:|
| t3_hypothesis | 0.424（−0.172 LOSE） | **0.532（−0.064 LOSE）** |
| t2_mode | 0.311（+0.135 WIN） | 0.311（+0.135 WIN・不変） |
| 8層平均 | 0.5469（+0.069） | **0.5604（+0.082）** |

弱5＝WIN4(mode/relation/quality/scene)・LOSE1(t3・引き分け寸前)、強3＝全 maintained。全800テスト緑。

## 限界

- **t3 は依然わずかに LOSE（−0.064）**: 残りは学習 conv/traffic/quiet 境界の真の弱さ（180対43 で一方的でない）＝research 領分。env_start/traffic→quiet_stable 等の混同が残る。**これ以上の seal 合わせ込みはしない**。
- mode の uncertain/side_rear_caution は clean な証拠署名が無く未補完（過適合回避）。
