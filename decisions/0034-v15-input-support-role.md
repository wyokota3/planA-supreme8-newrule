# ADR 0034: v1.5 入力対応 — Phase 0 プラミング ＋ T-Role（salience→6クラス role）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-006(role)・契約 `N04-scenario-contract/ns_epi_input_contract_v_1.5.md`(C-1c)・`docs/PLAN-v1.5-input-support.md`。
- エビデンス: coverage_v2(v1.5) vs coverage_v1(v1.4) の eval 比較・全800テスト緑。

## 背景

v1.5 契約は観測コンテキスト（episode / scene_state.stability / track salience,subtype）を追加。`t2_role` の
**source_human / source_object** は両実装で語彙 4 クラスのみ emit＝**0 固定**（coverage_v1/seal role 0.63 の天井）。
v1.5 の `salience` で主役（最大 salience の track）を観測から特定できる。

## 決定

**後方互換ゲート（presence-gated）** で v1.5 を消費。v1.5 フィールドが無ければ従来 v1.4 挙動（現行 0.6305 を不変に保つ）。

### Phase 0（入力プラミング・`core.py`）
- version: gate は `_SNAPSHOT_PREFIX="PSO-Snapshot/"` の prefix 判定で `PSO-Snapshot/1.5` を**既に受理**（変更不要）。
- 新ヘルパ（欠落=None=v1.4）: `_episode(snap)` / `_stability(snap)` / `_salient_kind(snap)`。

### T-Role（`core._role_evidence` ＋ `role.py`）
- `_role_evidence` に `salient_kind`（最大 salience track の category・None=v1.4）を追加。
- `role.role_logits`: `salient_kind` が在れば **緊急音(siren/alarm)絶対優先 → それ以外 argmax salience の category**
  （human→source_human / object→source_object / vehicle→source_vehicle / speech→source_speech / 他→unknown）。
  `salient_kind` 不在(v1.4)は従来の4クラス規則のまま。ADR 0033 の緊急音優先 tie-break と整合。

## 結果（eval・coverage_v1 vs coverage_v2）

| | coverage_v1 (v1.4) | coverage_v2 (v1.5) |
|---|---:|---:|
| role acc | 0.6324（不変） | **0.9598（+0.327）** |
| source_human (n=84) | 0.000 | **1.000** |
| source_object (n=158) | 0.000 | **1.000** |

- **0 固定だった source_human/object が復元**。supreme が 6 クラスを emit。
- **v1.4（coverage_v1）は完全不変**＝後方互換（seal 0.6305 保持）。全800テスト緑＋v1.5 role テスト7件追加。

## 限界・次

- 検証は coverage_v2/eval（同一シナリオ・入力 v1.4 vs v1.5 の controlled A/B）。**seal 最終確認は新 seal が望ましい**（同一 seal の多重検定回避）。
- 次: **T-Scene**（stability→scene_regime）/ **T-T3**（episode→会話×危険の conv_participating）。`PLAN-v1.5-input-support.md`。
- 過適合回避: GT 合わせ込みはしない（salience は観測 proxy で wiring のみ）。
