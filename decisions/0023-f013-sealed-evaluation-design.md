# ADR 0023: F-013 封印評価の設計 — 経路合成・PSO入力 seam・項目別 verdict

- 日付: 2026-06-14
- ステータス: 採用（Step 1 設計確定・ユーザー承認済み 2026-06-14。実装は WORKFLOW step2→8 で確定）
- 関連: SPEC `F-013` 節、`specs/GUARD_IF.md` §3、ADR 0010（決定2=経路合成の保留）、
  ADR 0012（評価指標式・全null層 overall）、ADR 0006（v1.4 語彙・baseline 再計測）、
  ADR 0022（supreme end-to-end ランナー）、`specs/TEST_STRATEGY.md`（F-013・穴2）

## 背景

F-013 はプロジェクトの最終目標（汚染ゼロの封印で supreme vs baseline を項目別に対比）。
着手にあたり ADR 0010 が「F-013 設計時に解決」と保留した経路合成、ADR 0012 が条件付けた
全null層の扱い、SPEC 境界条件の封印→PSO アダプタ・baseline 再計測 seam を確定する必要があった。
調査で、**封印レコード（GT_SCHEMA）は GT のみを保持し PSO 入力を持たない**ことが判明し、
入力源の seam を明示する設計判断が加わった。

## 決定（ユーザー承認済み・2026-06-14）

### 決定1: 経路合成 = SealStore に `open_eval_session` を新規追加（ADR 0010 決定2 の具体化）

F-013 の封印開封は唯一 `SealStore.open_eval_session(aggregate, session_id, issued_ts) -> OpenToken`
を経由する。内部実装は:

1. `gate = guard.SearchGate(self._guard)` … **store 自身の内包 guard** に SearchGate を被せる
   （ADR 0010 決定2 が指定した「store 側 guard を SearchGate に渡す」方向）。
2. `token = gate.open_token_for_eval(aggregate, session_id, issued_ts)` … aggregate 検査を**強制**
   （不合格は `guard.Blocked`・枠不消費）。store 自身の guard で発行するので、後続の
   `read_sealed_gt(..., token=token, ...)` がこのトークンを受理する。
3. `self._persist_session_state()` … 生涯開封セッション数を `session_state.json` に永続化
   （プロセス跨ぎ「生涯1回」担保・GUARD_IF 運用規約2）。

これにより ADR 0010 決定2 の「片肺問題」（SearchGate 経由は永続化されない／SealStore 直は
aggregate 素通し）を1メソッドに合成して解消する。`SealStore.issue_open_token` は F-013 経路では
**使わない**（GUARD_IF 運用規約5 を維持）。失効は既存 `revoke_open_token(token, revoked_ts=...)`。

### 決定2: PSO 入力源の seam（封印は GT のみ・着手条件4 の核心）

封印レコードは `meta`＋`gt`（正解ラベル）のみで、`read_sealed_gt` は GT だけを返す。
supreme 実走に要する **PSO-Snapshot 入力（input 契約 v1.4）は別系統**。sealeval は
**(a) PSO 入力**と**(b) 封印 GT** を `scenario_id` で対応づけて採点する。

- **build（本 WORKFLOW で作る範囲）**: ダミー封印 GT ＋ fixture PSO 入力で経路全体をドライラン
  （TEST_STRATEGY「ダミー封印で経路」・穴2）。本番封印は開けない。
- **本番の実 PSO 入力源の接続**は、baseline 再計測と同じ**研究者手動 seam** として最終実走時に
  確定する（決定3 と一貫）。封印→PSO アダプタ `seal_scenario_to_pso` はこの seam の境界に置く。

### 決定3: baseline 取り込み I/F（研究者手動・fixture 先行）

sealeval は baseline を実行しない。研究者が手動で再計測（risk_tier 210 規約・quality v1.4 語彙・
ADR 0012/0006）した baseline スコアを `load_baseline_scores(...)` で取り込み、supreme と
**同一 canonical_metric_spec の layer schema**で項目別対比する。テストは fixture で回す。
canonical layer と不一致な baseline 入力は停止（黙って採点しない）。

### 決定4: 全null層の扱い（ADR 0012 着手条件2）

封印で全null層（nonnull=0）が起きうる前提で、`harness.overall()` の「当該層を平均から除外」挙動を
**固定するテストを F-013 で追加**する。項目別対比は層ごとに行い、封印に当該層データが無い項目は
`no_data` として勝敗から除外する（draw 扱いにしない）。

### 決定5: 項目別 verdict（F-013-2・成功目標）

`compare_items(supreme, baseline, *, delta_strong, weak_items, strong_items)`:
- 弱い項目: `supreme - baseline > δ_strong` → win ／ `baseline - supreme > δ_strong` → lose ／
  `|Δ| ≤ δ_strong` → **draw**（引き分け）。
- 強い項目: `baseline - supreme > δ_strong` → degraded ／ それ以外 → maintained。
- δ_strong は U5b（暫定 0.02）。
- **verdict 境界の浮動小数点誤差は U5a/ADR 0002 の ε（`|a−b| ≤ 1e-9 + 1e-6·max(|a|,|b|)`）で
  draw/maintained 側へ吸収する**（`sealeval._exceeds_delta`）。十進境界（例 `0.62−0.60`）の二進表現
  誤差（~1.8e-17）を draw に倒し、genuine な差（δ を ~5e-4 以上超える）は ε（~2e-8）を遥かに上回り
  win/degraded を保つ。harness の連続値再現判定と同一 ε で方法論的に一貫（監査 R1・2026-06-14）。
- 「弱い5↑ ∧ 強い維持」は **成功目標フラグ**として report に載せるのみ。**合否ゲートにしない**
  （SPEC 非機能要件・2026-06-12 再分類）。統計的有意性 U11 は対象外（穴1）。

### 決定6: sealeval 公開面

| API | 役割 |
| --- | --- |
| `seal_scenario_to_pso(...)` | 封印シナリオ入力 → pso_snapshots アダプタ（決定2 の seam 境界） |
| `load_baseline_scores(...)` | baseline 取り込み I/F（決定3） |
| `compare_items(...)` | 項目別 verdict（決定5） |
| `run_sealed_evaluation(seal_store, aggregate, baseline_scores, *, scenario_ids, session_id, issued_ts, revoked_ts, weak_items, strong_items, delta_strong, config=None) -> SealEvalReport` | 封印を1回開封→全 GT を単一トークン下で read→supreme 実走＋`harness.score(canonical_metric_spec)`→baseline 取り込み→`compare_items`→revoke→`lifetime_session_count()==1` と `audit_seal_access` 合格を保証 |

時刻（issued_ts/revoked_ts/ts）は呼び出し側供給（GUARD_IF 運用規約4・決定的）。stdlib のみ。

## 影響

- 実装ループ: test-writer（`tests/test_F013_*.py`：同一指標・verdict 境界・単一開封セッション・
  経路合成・全null層固定・baseline I/F）→ implementer（`src/supreme/sealeval.py` 新規＋
  `SealStore.open_eval_session` 追加）→ auditor（封印保全・開封1回・同一指標を厳格に）。
- `SealStore` への `open_eval_session` 追加は ADR 0010 決定2 が予告した合成であり、F-002 仕様逸脱では
  ない（GUARD_IF §3 運用規約5 の正規経路化）。GUARD_IF に本メソッドを追記する。
- 本番実走（封印の生涯1回の開封）は build と別の意図的ステップ。PSO 入力源・baseline 値の
  研究者手動 seam を最終実走時に接続する。

## 申し送り（実装で確定/将来）

- U6（実施時期）: 前提（F-002/F-012/F-基盤-001）充足。実コードの本番実走時に確定。
- 本番 PSO 入力源アダプタの実データ接続・baseline 再計測値（研究者手動）。
- **R2（監査 2026-06-14・対処済み 2026-06-14）**: `run_sealed_evaluation` の開封前に窓内不変条件
  `issued_ts + max(0, len(scenario_ids)-1) < revoked_ts`（半開区間 `[issued_ts, revoked_ts)`）を
  fail-closed 検証し、不成立は `EvalWindowTooNarrow` で**開封前に停止**する（封印の生涯1回の枠を
  消費しない）。差分監査 `reports/audit-20260614-1540-F-013-R2-delta.md` で pass・R2 クローズ。
  - **障害像の補正（差分監査 R3a）**: 未対処時の実障害は「窓外 read で中断」ではなく、
    `SealGuard.is_access_allowed` が上端を見ない（`ts >= issued_ts` のみ）ため **read は完走し、
    開封枠を焼いた上で最後の `audit_seal_access` が半開区間突合で不合格**になる（silent failure・
    枠は消費済みで気づきにくい）。fail-closed 検証はこの実障害も防ぐため対処価値はむしろ補強される。
- 統計的有意性 U11（穴1）・封印保全のログ経由限界（穴8）は受容済み。
