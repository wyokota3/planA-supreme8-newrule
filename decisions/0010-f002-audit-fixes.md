# ADR 0010: F-002 監査指摘への対処 — 上書き拒否・公開復元API・保留2件の申し送り

- 日付: 2026-06-12
- ステータス: 採用
- 関連: `reports/audit-20260612-2238-F-002.md`、ADR 0008/0009、`specs/GUARD_IF.md`

## 背景

F-002 の監査(auditor=fable)で、テスト全パスでは検出されない機構穴2系統(高)+中リスク2件が指摘された。

## 決定(ユーザー承認済み・2026-06-12)

1. **封印済みレコードの上書き拒否(今回修正)**: 同一 scenario_id の再 `register` は
   `SealOverwriteError` で拒否し、**試行を access_log に記録**する(不可触の機構的担保)。
2. **SearchGate × SealStore の合成は F-013 まで保留**: F-013 が SearchGate 経由だと永続化が効かず、
   SealStore 経由だと aggregate 検査が素通しになる「片肺」問題は、**F-013 の設計時に解決する**
   (本 ADR で F-013 の着手条件として登録。SPEC F-013 節に注記)。それまで
   `SealStore.issue_open_token` を F-013 から直接使ってはならない。
3. **guard に公開復元APIを追加(今回修正)**: `SealGuard(*, production, initial_session_count=0)`。
   既定値付きキーワードのため既存契約は非破壊。復元値の型検証(非負整数)込み。
   sealset の private 属性依存(`_lifetime_session_count` への代入)を解消し、GUARD_IF に追記。
   F-014 テストにカバレッジを追加。
4. **リネージ検算素通り・逆方向交差(封印後の train 追加)は F-003 送り**: 検査統合点の割当てを
   F-003(増強・train 登録側)/F-012(探索)の着手条件として登録(SPEC F-003 節に注記)。
   推奨案として「sealset.register が governor にも meta 登録し datagov を単一リネージ権威にする」
   案を記録しておく(F-003 設計時に再評価)。

## 追記: 決定1・3の契約詳細(2026-06-13・ユーザー承認済み)

- **復元値の例外型**: `initial_session_count` の不正値(負数・非整数・bool・文字列等)は
  `GuardInputError`(guard 既存の入力エラー例外に統一)。
- **外部注入 guard の優先順位規約**: 公開復元API化により注入 guard へ状態ファイル計数を
  適用できない(構築時注入)ため、**production=True での `seal_guard` 注入は
  `GuardInputError` で拒否**(fail-closed)。本番は自前生成+状態ファイル復元のみ。
  dummy(production=False)は注入可だが、状態ファイル復元は自前生成時のみ(注入時は読まない)。
  F-013 の経路合成(決定2)は「store 側 guard を SearchGate に渡す」方向で設計する。
- **上書き試行の記録時刻**: `SealStore.register` に **keyword-only `ts` を必須追加**
  (省略 TypeError・GUARD_IF 運用規約4「時刻は呼び出し側供給」と一貫)。上書き試行は
  `{"session_id": None, "ts": float(ts), "target": scenario_id}` で access_log に記録
  (SealAccessRecord 契約の型どおり・session_id=None により監査突合も不合格になる tripwire)。
  既存 F-002 テストの register 呼び出しは test-writer が ts 付きへ機械的に更新する
  (テスト意図は変えない)。上書き拒否は production/dummy 共通(保管不変性はモード非依存)。

## 影響

- 修正ループ: test-writer(F-002 上書き拒否テスト+F-014 復元APIテスト)→ implementer
  (sealset 上書き拒否+ログ記録、guard 復元API、sealset 復元経路の公開API化)→ 差分再監査。
- `specs/GUARD_IF.md`: `initial_session_count` の追記+「F-013 は経路合成の解決まで
  issue_open_token を直接使用しない」注記。
- 既知の残存(監査記録済み・受容): 並行2インスタンスの計数競合(事後は access_log 突合で検出可)、
  session_state.json の改竄(穴8 と同種)、記録 I/O 失敗時の無記録。
- 低優先の意図的残置(差分監査 2026-06-13 で追跡登録・対処時期未定): 初回監査推奨 #7
  (GT_SCHEMA「フィルタの既定は F-002 で確定」の記述更新)、#8(access_log 読み戻しの型検査)、
  access_log 自体の改竄・削除が検出不能である旨の明文化(#5 の残り)。いずれか対処時は本 ADR を更新する。
