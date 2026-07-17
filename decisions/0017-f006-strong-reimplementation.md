# ADR 0017: F-006 強い項目の流用 — 独立再実装(U9 確定)・ルール層のみ

- 日付: 2026-06-13
- ステータス: 採用
- 関連: SPEC `F-006`/`U9`、ADR 0006(v1.4 語彙)、ADR 0012(評価指標・risk_tier 210/Anomaly 採点外)、
  ADR 0002(δ_strong=U5b)、baseline `external-data/planA-baseline/src/ns_epi/{t0.py,t1.py,t2.py}`、強い項目調査
- 決定者: ユーザー承認済み(2026-06-13・U9 と スコープの2問)

## 背景

F-006(強い項目 T0/T1/role の流用移植)step1。U9(流用形態: 物理コピー/submodule/再実装)が前提。
調査で baseline の T0/T1/role は**内部 import 連鎖ゼロ(stdlib のみ)**・HGF 依存は runner が float を渡す
データ依存(コード依存でない)と判明。複雑度: T0=純関数~30-40行、T1=状態機械~45行、role=logit 5ルール。

## 決定

### 決定1(U9): 独立再実装

supreme が T0/T1/role の判定ロジックを**独立再実装**する。「baseline と独立な新アーキ supreme」原則に
最も整合し、**F-006-2(実行時非リンク)を自然に満たす**。物理コピー(role は t2.py 768行コピーが必要・
来歴 U21)・submodule(F-006-2 違反リスク)は採らない。

### 決定2(スコープ): ルール層のみ(改良モジュールと同一流儀)

F-006 = T0/T1/role の**判定ルール**。証拠抽出(段1)・HGF・softmax/EMA(段3-4)は**上流共有基盤**で
スコープ外(F-013 の end-to-end でも必要)。T1 の `precision_weight_anom` は**入力パラメータ**(上流供給・
既定 0)。role は logit ルール(argmax は F-008 relation と同流儀)。

### 決定3: baseline ルールの忠実再現(δ_strong 目標)

強い項目は「下げない」(F-006-1: δ_strong=0.02 以内・F-013 で測定)が目標なので baseline ルールを忠実に再現:

**T0 (risk_tier・直接ルール・HGF非依存・状態レス)**:
- 主トラック選択: **siren 優先、なければ最近傍(最小 r_m)**。
- kind 別 (caution, danger) TTC 閾値: `vehicle/siren=(12.0,2.0)`, `alarm=(5.0,2.0)`, `speech=(2.0,1.0)`, `default=(5.0,2.0)`。
- `min_TTC ≤ danger閾値 → danger` / `≤ caution閾値 → caution` / それ以外 `info`。
- **siren 下限**: siren が info 判定なら caution へ引き上げ。
- **safety latch は risk_tier に適用しない**(下記「追記」で是正)。risk_tier は閾値テーブル + siren 下限のみ。
- 語彙 v1.4: `info / caution / danger`。

**T1 (t1_state・状態機械・状態保持)**:
- 入力: `ttc_s`(min_TTC)、`min_range_m`(全 track の最小 r_m・track 無しは 100.0)、`pw_anom`(既定 0)、`prev_t1`。
- `ttc_threshold = clamp(12 + pw_anom*3, [12,15])`、`appr = ttc_s < ttc_threshold`。
- **tick0(prev 無し)**: `appr → approach` / else `idle`(pass/depart は出さない)。
- **prev=approach**: `min_seen=min(prev_min_seen, cur_range)`、`diverged=(cur_range−min_seen)>1.0`、
  `incremented=(cur_range−prev_range)>0.3`。`diverged∧incremented∧cur<5.0 → pass` /
  `diverged∧incremented∧cur>10.0 → depart` / それ以外は閾値で `approach/idle`。
- **prev=idle**: 閾値のみで `approach/idle`。
- 状態 `(min_seen, prev_range, in_approach)` を次 tick へ持ち越す。
- 語彙 v1.4: `idle / approach / pass / depart`(GT 出現4・ADR 0012。enum の stop/repeat は採点語彙外)。

**role (t2_role・logit ルール)**:
- `has_siren ∨ has_alarm → source_alarm += 1.5`、`elif has_vehicle → source_vehicle += 1.5`(緊急音優先)。
- `conv_strong(has_speech ∧ speaking>0.7 ∧ min_range<5) → source_speech += 2.0`。
- `conv_weak(has_speech ∧ speaking>0.3 ∧ min_range<4 ∧ ¬conv_strong) → source_speech += 1.0`。
- `linked_speech_score>0.4 → source_speech += 1.5`。
- **無証拠既定**(role logit 全 0)→ `unknown += 1.5`。
- 語彙 v1.4: `source_speech/source_vehicle/source_alarm/source_human/source_object/unknown`(6)。
  baseline は source_human/source_object に発火ルールが無く出力されない(忠実再現・relation の departing/unrelated と同型)。
- argmax は role logit の最大(softmax/EMA は上流・スコープ外。F-008 relation と同流儀)。

### 決定4: F-006-2 独立性チェックを本機能で固定

supreme が baseline コードへ**実行時リンクしていない**ことの機械チェック(F-006-2)を F-006 のテストで固定する
(例: `supreme.t0/t1/role` 等が `external-data` / baseline パッケージを import しない・supreme パッケージ内で閉じる)。

## 影響

- F-006 は supreme の T0/T1/role ルール層を新規実装(独立再実装)。テストは合成入力 → 期待出力で baseline ルールを固定。
- 上流共有基盤(証拠抽出・HGF・softmax/EMA)は F-006 スコープ外(F-013 の end-to-end 前提)。
- 受け入れ条件 F-006-1(δ_strong 以内維持)は F-013 で測定。F-006-2(独立性)は本機能で機械チェック。
- Anomaly は強い採点項目でなく上流入力(ADR 0012 採点外)。本体移植は不要。T1 の pw_anom は入力パラメータ(既定 0)。

## 追記: T0 safety latch の是正(2026-06-13・監査 T0-1・ユーザー承認済み)

初版の決定3 T0 は safety latch(`min_TTC≤0.8 ∨ siren → danger`)を **risk_tier のルール**として
記述したが、これは baseline 実コードとの**乖離(誤記)**だった(監査 `reports/audit-20260613-2201-F-006.md` T0-1)。

- **baseline 実態**: safety latch は **`risk_safe`(数値特徴)のみ**に作用し、**採点される `risk_tier` には
  非適用**(`external-data/planA-baseline/src/ns_epi/t0.py` の latch は risk_safe 経路、採点 risk_tier は
  `_determine_risk_tier` の出力。runner も非 latch 値を採点)。
- **是正**: supreme の `risk_tier` から safety latch を**除去**する。risk_tier = **kind 別 TTC 閾値テーブル +
  siren 下限のみ**。siren の高 TTC フレームは siren 下限で **caution**(danger でない)= baseline 一致。
- **risk_safe は採点8層に含まれない数値出力**(ADR 0012 の8層に無い)であり、F-006(採点される強い項目)の
  **スコープ外**。risk_safe + latch が必要なら別途・将来(本 ADR では risk_tier のみ・latch なし)。
- 影響: 実トレースで siren=caution 54フレームの danger 誤上書きが解消し、F-006-1(δ_strong)の F-013
  リスクが下がる。修正ループ: ADR 是正 → test-writer(T0 テスト是正)→ implementer(latch 除去)→ 差分再監査。
- 軽微(監査・低): T0 の track 空配列は例外でなく安全側の既定(info 等)で扱う。T1 prev=idle の min_seen
  初期化は baseline と揃える(下記 implementer 指示)。

## 残件・申し送り

- **baseline 数値一致(δ_strong≤0.02)の確認は F-013 待ち**。再実装の忠実度は F-013 計測で最終確認(成功目標)。
- T1 の `precision_weight_anom`(Anomaly-HGF 由来)を既定 0 とした場合の baseline 一致への影響は ttc_threshold が
  [12,15] にクランプされ最大±3秒の差。完全一致が要る場合は上流 Anomaly-HGF 基盤の供給が前提(別課題)。
- 上流共有基盤(証拠抽出・HGF・softmax/EMA)の supreme 実装は未着手(mode/relation/quality/role 共通・F-013 前提)。
- 穴7(強い項目の累積劣化): 複数の弱い項目改良が少しずつ強い項目を削る累積は単発 δ_strong では捉えられない(ベースライン固定の累積監視は未設計・F-013/運用課題)。
