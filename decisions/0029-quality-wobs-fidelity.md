# ADR 0029: quality 忠実度ギャップ修正 — 観測信頼度 w_obs の忠実再現

- 日付: 2026-06-15
- ステータス: 採用（監査 pass・`reports/audit-20260615-0715-quality-B.md`）
- 関連: ADR 0014（F-011 quality 再較正）、ADR 0022（観測式）、ADR 0024/0026（観測式/HGF）、
  `reports/quality-diagnose-20260615-0706.md`（診断）、baseline `runner._extract_quality_inputs`（spec の w_obs 定義）

## 背景

旧 supreme（l04-ours）比較で quality_regime が新 **0.7238** vs 旧 **0.7619** と劣後。診断で **(B) 忠実度ギャップ**
と確定: `core._quality_obs_raw_logits` が観測信頼度 `w_obs` を固定 `_DEFAULT_WOBS=0.5` にハードコードし、
PSO track の `w_obs` を読んでいなかった。baseline は **全 track（audio+humans+objects）の w_obs 中央値
（w_obs を持つ track のみ・1つも無ければ 1.0）**。固定 0.5 が系統的に h_q を押し下げ **GOOD→DEGRADED 43件**。

## 重要な訂正（v1.3/v1.4 採点）

「旧 supreme 0.7619」は l04-ours を **v1.3 語彙**で exact-match 採点した値。本診断・SPEC は **v1.4 語彙**で採点する。
**同一 v1.4 採点では旧 supreme（l04-ours）も 0.8238**。つまり見かけの −0.038 は v1.3/v1.4 跨ぎの採点差を含み、
v1.4 同一土俵での真のギャップは **−0.10（0.7238 vs 0.8238）**で、その全量が w_obs 忠実化で消える
（**3者一致**: 新 supreme 修正後 = 旧 supreme v1.4 = baseline 専用HGF 忠実 sim = **0.8238**）。

## 決定

`core._quality_obs_raw_logits` の w_obs を `_w_obs_bar(snap) = median(track の w_obs)`（無し=1.0）へ忠実再現。
係数・GOOD/BLOCK 境界・vol（var1）・HGF は無改変。w_obs 中央値は実 track 信頼度（[0.09,1.0] 分布・182/210 で
track 在り）で、v021_core 合わせ込みでない（恒久規則の再現）。

## 影響（全層＋CV 検証）

- **quality_regime: 0.7238 → 0.8238（+0.100・旧 supreme v1.4 値一致）**。
- 波及（h_q 経由）: t2_mode +0.0048・t3 +0.0047 の微増のみ・他層不変。**悪化層ゼロ**。
- **学習層 CV held-out**: t3 0.5333→0.5381（全 fold 非悪化）・scene 不変。in-sample 楽観でなく held-out（正準）で悪化なし。
- quality 偽陽性の純益: GOOD 回復 +23 vs 偽陽性 +4・**BLOCK 漏れ 0** = 純益正。
- 回帰テスト `tests/test_quality_wobs.py`（5件）追加で「高/低/無/中央値」を end-to-end で pin（平均実装・旧 0.5 を棄却できることも実証）。800テスト全緑。
- すべて in-sample/CV（v021_core）値。最終確定は封印（F-013）。

## 申し送り（監査記録）

- **コメント腐れ（低優先）**: `core.py` の w_obs 近傍コメントが「平均・既定 0.5」のまま（実装は中央値・既定 1.0）。次に core を触る際に是正。
- baseline 一次ソース（`external-data/planA-baseline`）は作業ツリーに vendored されておらず、監査は ADR 0022 観測式＋診断の baseline 再実装写し（両者一致）で忠実性を判定。一次突合は planA-baseline チェックアウト環境で。
