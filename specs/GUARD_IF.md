# GUARD_IF — ガードレール(F-014)のインターフェース契約

> F-014 完了時(2026-06-12)に確定した `supreme.guard` の公開契約。
> **F-002(封印アクセスログの生成)・F-012(選定来歴の生成・探索ゲート)・F-013(開封トークンの利用)は本契約に従う。**
> 経緯: ADR 0002(開封トークン方式)→ ADR 0007(fail-closed①・機構のみ④・テスト駆動定義)→
> ADR 0008(監査対処: production 明示必須・経路統合ほか)。
> 監査: `reports/audit-20260612-2041-F-014.md`(初回)/ `reports/audit-20260612-2125-F-014-delta.md`(差分・done判定)。

## 1. 公開 API(`supreme.guard`)

| API | 役割 | 重要規約 |
| --- | --- | --- |
| `check_param_budget(param_count, data_count, k=None) -> GuardResult` | ガードレール①(過学習) | 合格 ⇔ k 供給済み ∧ `param_count < data_count×k`(厳密 `<`)。**k=None・不正値は checked=True の不合格(fail-closed)**。k の値とパラメータ数の数え方は U24 |
| `SealGuard(*, production: bool, initial_session_count: int = 0)` | ②封印トークン制御 | **production はキーワード明示必須(既定なし・省略 TypeError)**。本番封印は必ず `production=True`。`initial_session_count` は生涯計数の**復元用・構築時注入**(既定 0 で非破壊)。**不正値(負数/非整数/bool)は `GuardInputError`**(検証は dummy でも走る・ADR 0010 決定3) |
| `SealGuard.issue_token(session_id, issued_ts, *, precheck_passed) -> OpenToken` | トークン発行(低レベル基本操作) | precheck_passed は自己申告 bool のため**アプリケーションコードから直接呼ばない**(正規経路は SearchGate)。不合格時 `PrecheckFailed`(枠不消費)。production の2回目発行は `SessionLimitExceeded` |
| `SealGuard.revoke_token(token, *, revoked_ts)` | 失効(F-013 終了時) | **revoked_ts 必須**(省略 TypeError) |
| `SealGuard.is_access_allowed(token, ts) -> bool` | 窓内判定 | 窓は**半開区間 `[issued_ts, revoked_ts)`**(`ts==revoked_ts` は窓外) |
| `SealGuard.lifetime_session_count() -> int` | 生涯開封セッション数 | 発行成功時のみ加算 |
| `audit_seal_access(log, token) -> GuardResult` | ②ログ突合 | 全レコードが token.session_id 一致かつ窓内で合格。1件でも違反(別session/窓外/session_id=None)で不合格 |
| `check_selection_purity(provenance, seal_access_log=None) -> GuardResult` | ③選定純度 | 全 `split=="train"` で合格。log 未供給時は reason に**「封印アクセス検査は未実施」を明記**(供給済み空の「0件」と区別) |
| `check_trial_cap(trial_count, cap=None) -> GuardResult` | ④撤退基準(候補) | **cap=None は checked=False(未検査・合否不算入・reason に U18 明示)**。cap 不正値(負数・非整数・bool)は checked=True の不合格 |
| `combine_guards(results) -> AggregateResult` | 集約 | checked=True の全合格で合格。**空リストは不合格**(fail-closed) |
| `SearchGate(seal_guard)` | 後続ゲート(SealGuard を内包) | F-012/F-013 はこれを経由する |
| `SearchGate.request_continue(aggregate) -> bool` | 探索続行可否(F-012) | aggregate 不合格 → False(ブロック) |
| `SearchGate.open_token_for_eval(aggregate, session_id, issued_ts) -> OpenToken` | **封印開封の唯一の正規経路**(F-013) | 内包 SealGuard 経由で発行し**生涯計数を必ず消費**。aggregate 不合格 → `Blocked`(枠不消費) |
| 例外 | `GuardInputError` / `PrecheckFailed` / `SessionLimitExceeded` / `Blocked` | |

## 2. レコード契約

### GuardResult(全ガード共通)
`passed: bool` ／ `guard_id: str`("F-014-1".."F-014-4") ／ `checked: bool`(実検査したか。④の cap 未供給のみ False) ／ `reason: str`(非空・人間可読)

### AggregateResult
`passed: bool` ／ `results: tuple[GuardResult]` ／ `blocked_by: tuple[str]`(不合格だった checked ガードの guard_id) ／ `reason: str`

### OpenToken
`session_id: str` ／ `issued_ts: float` ／ `revoked_ts: float|None` ／ `active: bool`(未失効で True)

### SealAccessRecord(封印アクセスログ1件・**F-002 が生成**)
dict `{"session_id": str|None, "ts": float, "target": str}`
- 有効トークン下のアクセスはその session_id、**トークン無し不正アクセスは None** を記録する
- `ts`/`target` は必須・型どおり(**不正形レコードの検査前バリデーションは guard の責務外**。生成側=F-002 が
  本契約に適合するレコードのみを書く。guard は不正形に対し未捕捉例外を出しうる — 既知限界 R1)

### SelectionProvenanceRecord(選定来歴1件・**F-012 が生成**)
dict `{"eval_id": str, "split": str, "scenario_id": str, "score": float}`
- `split` は「その評価に使ったデータの split」("train"/"seal"/"unassigned")

## 3. 運用規約(F-013 向け・重要)

1. 本番封印評価は **`SealGuard(production=True)` を単一インスタンス**で用い、`SearchGate` 経由でのみ開封する。
2. 生涯開封セッション数のスコープは **SealGuard インスタンスの寿命(プロセス内)**。プロセスを跨ぐ
   「生涯1回」の最終保証は、F-002 のアクセス制御と**永続化されたセッションID付きログ**を
   `audit_seal_access`+`lifetime_session_count` で突合して担保する(インメモリ計数のみに依存しない)。
   - **プロセス跨ぎ復元の実装手段**: F-002(`SealStore`)が自前生成時に永続セッション状態
     (`session_state.json`)を先に読み、`SealGuard(production=..., initial_session_count=読んだ計数)`
     で**構築時注入**して復元する(private 属性 `_lifetime_session_count` への代入は廃止・ADR 0010 決定3)。
   - **production での guard 外部注入は禁止**(`SealStore(production=True, seal_guard=...)` は
     `GuardInputError`)。構築時注入のため注入 guard へ状態ファイル計数を適用できず、本番封印の
     生涯1回を取りこぼすため fail-closed で拒否する。本番は自前生成＋状態ファイル復元のみ。dummy は
     注入可だが状態ファイル復元は自前生成時のみ(注入時は読まない)。
3. F-013 終了時は必ず `revoke_token(token, revoked_ts=終了時刻)` でトークンを失効させる。
4. 時刻(`issued_ts`/`revoked_ts`/`ts`)はすべて呼び出し側が供給する(guard は時計を持たない・決定的)。
5. **F-013 は `SearchGate` × `SealStore` の経路合成の解決(ADR 0010 決定2・F-013 着手条件)まで、
   `SealStore.issue_open_token` を直接使用しない**(`SearchGate` 経由の aggregate 検査を素通しにしないため)。
   開封の唯一の正規経路は `SearchGate.open_token_for_eval`。

## 4. 既知の限界(設計上受容・監査記録済み)

- **R1**: 不正形レコード(ts=None 等)は未捕捉例外になりうる(生成側の契約遵守が前提)
- **R2**: `issue_token` 直接呼び出しは precheck が自己申告(低レベル操作と明記済み。正規経路は SearchGate)
- **R3**: `OpenToken` の直接生成は防げない(Python の制約)
- **R4**: 生涯計数はインメモリ(上記 運用規約2 で補完 — F-002 が `session_state.json` を読み `initial_session_count` で構築時注入して復元する・ADR 0010 決定3)
- **R5**: ログに出ないアクセスは検出不能(テスト戦略・穴8。技術ロックは未設計)
