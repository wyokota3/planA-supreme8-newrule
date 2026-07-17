# ADR 0014: F-011 quality_regime 再較正 — GOOD ゲート h_q≥0.93(計測根拠)

- 日付: 2026-06-13
- ステータス: 採用
- 関連: ADR 0013(U1: quality=ルール改良)、ADR 0006(v1.4 語彙・順位シフト)、
  `reports/erroran-20260612-F005.md`(quality 較正問題)、baseline `external-data/planA-baseline/src/ns_epi/{quality.py,hgf.py,runner.py}`、
  h_q/vol 計測(本 ADR で記録)
- 決定者: ユーザー承認済み(2026-06-13・スコープ+進め方の2問)

## 背景

F-011(quality_regime 改良)の step1。スコープは**規則の再較正に絞る**(h_q/vol を入力とする
判定規則のみ・観測式+HGF は上流の別扱い)とユーザーが決定。再較正閾値の根拠化のため、
planA-supreme の quality 出力(acc 0.7619・F-005 と一致)を GT データに対し計測した
(再走 h_q は trace.json 格納値と**完全一致**=計測の健全性確認済み)。

## 計測結果(静的仮説を一部覆す)

- **vol(=sigma1)は全210フレームで 0.0058〜0.0099 に張り付き、0.01 も 0.05 も超えない**。
  - GOOD ゲートの `vol<0.01` は**常に充足** → GOOD→PASS を妨げるのは `h_q<0.94` の一点のみ。
  - 早期BLOCK ルール2(`vol>0.05`)は**一度も発火せず** → 静的調査の「vol 非対称ゲート」仮説は
    実データでは不成立。
- 悲観ズレ群の h_q 分布:
  - GT=GOOD→pred=PASS(23件): h_q 0.592 / 中央 0.916 / max **0.939**。
  - GT=DEGRADED→pred=BLOCK(13件): h_q 0.0014 / 中央 0.0035 / max **0.026**(ルール1 `h_q<0.25` が正しく捕捉)。

## 決定

### 決定1: F-011 のスコープ = 判定規則のみ(観測式+HGF は上流)

F-011 = supreme 独自の **quality_regime 判定規則**。入力 `(h_q, vol)`、出力 **v1.4 3クラス
`{GOOD, DEGRADED, BLOCK}`**。h_q/vol の生成(観測式+HGF)は**上流の共有基盤**であり F-011 に含めない。

### 決定2: 再較正 = GOOD ゲート h_q≥0.94 → **h_q≥0.93**(vol 条件は据え置き)

計測根拠: GOOD→PASS 23件のうち h_q∈[0.93,0.94) の **8件が GOOD に復帰、副作用0件**
(真 PASS 群の最大 h_q=0.925 < 0.93 のため巻き込みなし)。acc **0.7619 → 0.8000**。
vol 条件(`vol<0.01`・`vol>0.05`)は本データで不作動のため**動かさない**(死に条件だが faithfulness
のため構造は保持)。

### 決定3: v1.4 3クラス規則(baseline `_hq_to_regime` を順位シフト+GOOD 再較正)

baseline の判定構造を v1.4 へ順位シフト(ADR 0006: 旧 PASS→DEGRADED、旧 DEGRADED→BLOCK)し、
GOOD ゲートのみ再較正した規則(優先順位チェーン):

```
入力: h_q ∈ [0,1], vol ≥ 0
1) h_q < 0.25                  → BLOCK     # 旧 BLOCK
2) h_q < 0.40 ∧ vol > 0.05     → BLOCK     # 旧 早期BLOCK(本データ不作動・構造保持)
3) h_q < 0.55                  → BLOCK     # 旧 DEGRADED → v1.4 BLOCK
4) h_q ≥ 0.93 ∧ vol < 0.01     → GOOD      # 旧 GOOD・再較正 0.94→0.93
5) その他                       → DEGRADED  # 旧 PASS → v1.4 DEGRADED
```

挙動として等価な最小形は「h_q<0.55→BLOCK / h_q≥0.93∧vol<0.01→GOOD / その他→DEGRADED」。
テストは**挙動**(h_q,vol→v1.4 regime)を契約とし、内部の分岐保持/簡約は実装裁量。

### 決定4: DEGRADED→BLOCK 13件 = F-011 スコープ外(観測式/HGF の別課題)

これらは h_q≈0.001〜0.026 と極端に低く、ルール1 が正しく BLOCK にしている。閾値を下げると安全側の
意味を失う。本丸は**観測式 β/τ または HGF パラメータが DEGRADED 相当入力で h_q を ~0 まで潰す感度問題**で、
「規則の再較正」(F-011 スコープ)の外。**観測式/HGF 再較正の別タスクとして申し送る**(将来の F-011 拡張
または新機能)。

## 影響

- F-011 は supreme の quality_regime 規則(GOOD ゲート h_q≥0.93・v1.4 3クラス)を実装。テストは
  合成 `(h_q, vol)` → 期待 v1.4 regime で、GOOD ゲート境界(h_q=0.93 で GOOD・0.929 で DEGRADED)と
  計測由来の代表ケースを固定。
- 受け入れ条件 F-011-1(F-013 で項目別対比が測定・報告)は F-013 で測る。F-011 単体は規則の正しさを固定。
- h_q/vol 生成基盤(観測式+HGF)は F-011 スコープ外。F-013 の end-to-end には上流(観測+HGF 基盤)が要る。

## 残件・申し送り

- **観測式/HGF の感度再較正(DEGRADED→BLOCK 13件)**は別タスク。h_q を ~0 に潰す観測式 β/τ・HGF
  パラメータの見直し(F-011 スコープ外・将来)。
- **h_q/vol 生成基盤**(観測式+HGF)の supreme 実装は未着手。F-010(scene)も HGF を要するため、
  共有基盤として別途設計が要る(F-013 の end-to-end 前提)。
- baseline 参照スコアの v1.4・210規約 再計測(研究者手動・ADR 0012/F-013 まで)。
- 計測値(+8件・副作用0・0.7619→0.8000)は planA-supreme v1.3 出力での measurement。supreme 独立
  実装後の h_q/vol 分布で最終確認する前提(F-013)。
