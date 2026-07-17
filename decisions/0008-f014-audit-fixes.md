# ADR 0008: F-014 監査指摘への対処 — production 明示必須化・発行経路統合ほか

- 日付: 2026-06-12
- ステータス: 採用
- 関連: `reports/audit-20260612-2041-F-014.md`、ADR 0002/0007、`src/supreme/guard.py`

## 背景

F-014 の監査(auditor=fable・2026-06-12)で、封印保全の核に関わる重大指摘が出た。
最重点は「SealGuard の production 既定 fail-open」を巡る**三重の矛盾**(テスト docstring=既定True宣言
／テスト本体=裸 SealGuard() で2発行要求／実装=docstring を書き写しつつ署名は =False)。
加えて発行経路の分裂(F-013 向け経路が生涯計数を消費しない)など計7系統。

## 決定(ユーザー承認済み・2026-06-12)

1. **`production` の既定を廃止しキーワード明示必須化**(省略は TypeError)。書き忘れ事故を構造的に不可能に
   する(監査の推奨案A)。テスト側は裸 `SealGuard()` を `production=False` 明示へ修正し、矛盾 docstring・
   死にコード残骸を除去、省略時の陰性テストを追加。
2. **発行経路の統合**: SearchGate が SealGuard を内包し、`open_token_for_eval` は必ず SealGuard 経由で
   発行して**生涯計数を消費**する。事前検査は AggregateResult を直接受ける(自己申告 bool の経路を残さない)。
   不合格(Blocked)時はセッション枠を消費しない。
3. **トークン窓は半開区間 [issued_ts, revoked_ts)** に確定(ts==revoked_ts は期間外=fail-closed 側)。
   両端の境界テストを追加。
4. **`revoke_token` の `revoked_ts` を必須化**(省略時に窓が一点退縮し正当アクセスが遡及不合格になる
   運用罠の除去)。
5. **③選定純度の reason を真実化**: `seal_access_log=None` 時は「封印アクセス検査は未実施」と明記
   (虚偽の「0件」報告を排除)。来歴・ログが自己申告依存である限界(テスト戦略・穴8と同種)を文書化。
6. **`combine_guards([])` は不合格**(空虚合格の排除・fail-closed)。
7. **④の cap 不正値(負数・非整数・bool)は checked=True の不合格**(①の不正値処理と同形)。

## 教訓(プロセス)

- implementer がテスト内矛盾を**報告せず黙って fail-open に解消**した(エージェント規約の矛盾報告義務違反)。
  以後、サブエージェントへの依頼文には「矛盾発見時は停止・報告」を明示的に再掲し、監査観点にも
  「黙殺された矛盾がないか」を含める。
- 同一ファイル内の docstring と本体の矛盾はレビュー(ステップ3)でも見逃された。方法論の核に関わる
  テストは docstring と本体の整合チェックを監査の定常観点とする。

## 影響

- テスト改修(test-writer)→実装修正(implementer)→差分再監査の修正ループを実施。
- 確定後のレコード/API契約は `specs/GUARD_IF.md` として文書化し、F-002/F-012/F-013 が従う。
