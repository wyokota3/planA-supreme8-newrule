# ADR 0006: U7 解決 — 契約 v1.4 系への移行と採点語彙・契約適合方針の確定

- 日付: 2026-06-12
- ステータス: 採用（ADR 0005 の語彙運用を改訂）
- 関連: `specs/SPEC.md`(U7/U4/F-006〜F-011/用語集/制約)、`specs/GT_SCHEMA.md`(t2.mode・quality_regime)、
  ADR 0005、spec-reviewer による契約精査(2026-06-12)

## 背景

U7（契約中身の精査）を spec-reviewer（fable）で実施した。判明した事実:

1. **入力契約 v1.3→v1.4 は version 文字列のみの差**（構造・意味は同一と契約自身が明記）。
2. **出力契約 v1.3→v1.4 は意味変更を含む**: t2.mode の2クラスリネーム
   （`alert_observation`→`side_rear_caution`、`conv_participation`→`uncertain`）と、
   quality_regime の**順位シフト**（`GOOD|PASS|DEGRADED` → `GOOD|DEGRADED|BLOCK`。
   旧 PASS→DEGRADED、旧 DEGRADED→BLOCK）。契約は「参照スコアの再測定が必要」と明記。
3. 正準GT（feat @ a0b8822・ADR 0005）・baseline 実走・練習データ入力はすべて **v1.3 系**
   （PSO-Snapshot/1.3・PASS×32・BLOCK×0 を全数 grep で確認）。
4. **RESET_T3 / EPISODE_SWITCH は両版の契約に存在しない**（EPI-CTRL は preempt/resume/
   suppress/unsuppress/rate_limit のみ）。
5. Anomaly の出力スロットは契約に無い（最近傍: EPI-NOVEL / T0.novelty）。
6. 文書の事実誤り2件（SPEC「実入力 1.4 確認済み」/ GT_SCHEMA「観測値例 GOOD/BLOCK」）と
   用語の取り違え（「EPI入力」。入力レコードの実名は PSO-Snapshot/Delta）。

## 決定（ユーザー承認済み・2026-06-12）

1. **supreme は v1.4 系へ移行する**（採点語彙・契約とも v1.4 を正とする）:
   - 入力: PSO-Snapshot/Delta。**version は 1.3/1.4 両受理**（構造同一のため読み替えのみ）。
   - 採点語彙: **v1.4 統制語彙**（mode: side_rear_caution/uncertain を含む10クラス、
     quality: GOOD/DEGRADED/BLOCK、scene: STABLE/CHANGING/DEGRADING）。
   - 正準GT は引き続き feat 1.4.0（role/relation 追加 GT）だが、**取込時に契約定義の
     機械マッピング（mode 2クラスリネーム＋quality 順位シフト）で v1.4 語彙へ変換**して使う。
   - **baseline 参照スコアは v1.4 語彙で再測定が必要**（実行は研究者の手動領分・F-013 までに。
     既存の F-005 分析は v1.3 語彙時点のスナップショットとして有効、読替え注記を付した）。
2. **リセット命令（RESET_T3/EPISODE_SWITCH）は supreme 内部IFとして契約外定義**。
   発生源・粒度・エピソード境界（契約の episode_id/episode_status との関係）は U4 で確定。
3. **契約上「任意」のフィールド（geom/scene_state 等）は欠落時縮退**（情報なしとして扱う）。
   v021 実データでは全フレーム存在・Delta ゼロ・fields_ref ゼロという観測事実は記録するが
   前提化しない。Delta/fields_ref は当面非対応を明示エラーで表明。
4. **契約必須フィールドは全て出力する**（契約適合。T2 relevance・T3 posterior・thread_id 等
   採点対象外も出す。値の品質保証は採点8層のみ）。契約適合チェックは F-006 以降の
   受け入れ条件に追加できる。
5. 付随確定: Anomaly の対応付けは U10 で定義（候補: EPI-NOVEL / T0.novelty）。supreme 出力の
   mode/roles/relations キー集合は統制語彙に閉じる（開いた辞書にしない）。
   文書の事実誤り2件と用語（「EPI入力」→「PSO入力」等）は本 ADR とともに修正。

## 却下した代替案

- **v1.3 系で統一**（オーケストレーター推奨案だった）: baseline 実走・正準GTと同一土俵で追加作業ゼロ
  だが、ユーザーは最新契約 v1.4 への移行を選択。再測定の作業はユーザーが負担する。
- 契約拡張提案（リセット命令）: 上流変更待ちが発生するため却下。

## 影響

- `specs/SPEC.md`: U7 解決済み化・U4 注記・F-006〜011 の入力表記修正・用語集修正・制約更新。
  残ブロッカーは **U10 のみ**。
- `specs/GT_SCHEMA.md`: t2.mode キー集合を v1.4 語彙へ（**ADR 0005 直後の feat 語彙化を再改訂**）。
  quality/scene の統制語彙明記。v1.3 系生データは取込前マッピング必須を明記。
- F-001 実装/テスト: mode クラス定数を v1.4 語彙へ再同期。
- `scripts/run_erroran.py`: feat GT を生のまま読むため、**語彙マッピング実装までは現行 datagov
  バリデーションと不整合**（再実行時はマッピング追加が必要。次のデータ系機能 F-002/F-003 で対応）。
- `reports/erroran-20260612-F005.md`: v1.3 語彙スナップショットである旨の読替え注記を追加。
