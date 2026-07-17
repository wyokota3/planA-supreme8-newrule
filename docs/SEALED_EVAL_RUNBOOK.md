# 本番封印評価 運用 Runbook（F-013 最終実走）

> **対象**: 研究者（本番封印の生涯1回の開封を実施する人）。
> **目的**: 汚染ゼロの本番封印で supreme vs baseline を同一指標・項目別に対比する**最終実走**の手順。
> **状態**: コードの build は完了（`src/supreme/sealeval.py` ＋ `SealStore.open_eval_session`・全740テスト緑）。
> ここに残るのは **ADR 0023 が「研究者手動 seam」と明示した2点（実 PSO 入力源・baseline 再計測値）の接続**のみ。
> 設計根拠: `decisions/0023-f013-sealed-evaluation-design.md`、`specs/GUARD_IF.md` §3、`specs/SPEC.md` F-013 節。

---

## 0. 前提（すべて充足済み）

- F-002（封印セット）/ F-012（組み合わせ確定）/ F-基盤-001（end-to-end ランナー）/ F-014（guard）すべて done。
- `sealeval` は **封印を1回だけ開封**（`open_eval_session` 単一経路）し、全 GT を単一トークン下で read → supreme 採点＋baseline 取り込み → 項目別 verdict → revoke する。
- **本番封印は生涯1回しか開けない**。本 runbook の手順5以降は**取り返しがつかない**。先に手順1〜4（封印を開けない準備）を完了し、ドライランで経路を確認してから実施すること。

## 1. ⚠️ 研究者手動 seam（2点）— 実走前に必ず用意

ADR 0023 決定2/3 が build 範囲外とした2点。ここだけは人手で接続する。

### seam-1: 実 PSO 入力源 ＋ 実アダプタ
封印レコードは **GT（正解ラベル）のみ**保持し、supreme 実走に要る **PSO-Snapshot 入力は別系統**（input 契約 v1.4）。
- 現在の `sealeval.seal_scenario_to_pso(...)` は **決定的スタブ**（会話証拠フレームを合成するだけ・ドライラン用）。
- **本番では、封印シナリオの実観測タイムラインを PSO-Snapshot/1.4 形へ変換する実アダプタに差し替える**こと。出力は `core.run_supreme(snaps)` が 8層 view を返せる正当な Snapshot 列で、封印 GT とフレーム対応すること（決定的・乱数/時刻なし）。
- 実観測の所在（scenario source）は研究者が指定する（例: `external-data/.../scenarios/v021_core/<id>/`）。

### seam-2: baseline 再計測値（risk_tier 210 規約・quality v1.4 語彙）
- baseline は **sealeval が実行しない**（自動化対象外）。研究者が手動で baseline を回し（**risk_tier 分母 210・quality v1.4 語彙**・ADR 0012/0006）、**封印と同一シナリオ**でのスコアを得る。
- 結果を **canonical 8層の dict**（`{layer: acc[0,1]}`）に整える。8層 = `risk_tier / t1_state / t2_mode / t2_role / t2_relation / t3_hypothesis / quality_regime / scene_regime`。**Anomaly は採点外**（混ぜると `BaselineSchemaMismatch` で停止）。
- baseline 入力に封印シナリオを流すときも **seam-1 の封印→PSO アダプタ**を使う（SPEC F-013 境界条件）。

## 2. ドライラン（封印を開けずに経路全体を確認）

本番前に、ダミー封印（`production=False`）で `run_sealed_evaluation` を通し、`lifetime_session_count()==1`・`audit_passed==True`・項目別 verdict が出ることを確認する（`tests/test_F013_single_session.py` と同じ構成）。実アダプタ・実 baseline 値を**ダミーに差したまま**配線だけ検証する。

## 3. guard 集約（aggregate）を用意

開封は aggregate 合格時のみ。F-014 の検査を集約する（不合格は `guard.Blocked` で開封枠を焼かず停止）。

```python
from supreme import guard
g_param = guard.check_param_budget(param_count=<総学習param数>, data_count=<練習用件数>, k=<U24 で確定した係数>)
g_pure  = guard.check_selection_purity(<F-012 の選定来歴>, seal_access_log=<封印アクセスログ>)
aggregate = guard.combine_guards([g_param, g_pure, ...])   # 必要な検査を全て入れる
assert aggregate.passed, aggregate.reason
```

## 4. 時刻パラメータ（R2 窓内不変条件）

read ts は `issued_ts` から scenario ごとに +1.0 で割り当てる。**全 read が窓内に収まる条件**:

```
issued_ts + max(0, N-1) < revoked_ts     # N = len(scenario_ids)・半開区間 [issued_ts, revoked_ts)
```

満たさないと `sealeval.EvalWindowTooNarrow` で**開封前に停止**（封印枠を焼かない・監査 R2）。**revoked_ts は余裕を持って十分大きく**取ること（窓は時刻の数直線上の区間であって実時間ではない＝大きく取ってよい）。

## 5. 本番実走（⚠️ 生涯1回の開封）

### 5-0. 開封前に学習する（ADR 0025 Phase1b・**練習データのみで fit・封印は使わない**）

封印を開ける前に、**練習データ**（封印ではない開発/練習シナリオ。例: `v021_core`）で supreme を学習し、学習済み params を `run_sealed_evaluation(..., params=trained)` へ渡す。これにより封印 verdict が学習の利得を反映する（Phase1 までは封印評価が未学習の既定で動いていた＝監査 P1-R4）。

```python
from supreme import core

# 練習データ（封印では断じてない）で学習する。封印 GT/入力は一切使わない。
#   practice_scenarios = {scenario_id: pso_snapshots}（練習用 PSO-Snapshot 系列）
#   practice_gt        = {scenario_id: [gt_view, ...]}（練習用 8層 GT・t3/scene を採点キーに）
trained = core.fit_supreme(practice_scenarios, practice_gt)   # SupremeParams（学習済み t3/scene）
```

- **学習は練習データのみ・封印は評価専用**（seal を学習に使わない＝過学習ガード）。封印を学習信号に使うと汎化の正直な推定が崩れ、最終 verdict が楽観方向へ歪む（ADR 0025 決定3・封印は不可触）。
- 学習対象は **t3 / scene のみ**（ADR 0025 決定2）。learnable param 数（t3=6 + scene=3）は練習採点フレーム数を遥かに下回り F-014 ガードを満たす。
- **過学習の警告**: 練習データでの in-sample 利得（train=eval）は楽観値。汎化の正直な推定は CV held-out（`reports/cv-train-*.md`・lineage-disjoint・scene 0.557 / t3 0.410）を見ること。封印 verdict は別物（汚染ゼロの最終確定）。
- 後方互換: `params` を省略（または `None`）すると**従来どおり未学習の既定で実走**する（既存挙動を一切変えない）。

### 5-1. 封印で評価する（生涯1回の開封）

```python
from supreme import sealset, sealeval

# 実 PSO アダプタへ差し替え済みの sealeval を使う（seam-1）。
store = sealset.SealStore(root_dir=<本番封印の専用ディレクトリ>, production=True)  # 自前生成・状態ファイル復元

WEAK   = ("t2_mode", "t2_relation", "t3_hypothesis", "scene_regime", "quality_regime")
STRONG = ("risk_tier", "t1_state", "t2_role")

report = sealeval.run_sealed_evaluation(
    store,
    aggregate,                       # 手順3（合格必須）
    baseline_scores=<seam-2 の8層 dict>,
    scenario_ids=<封印シナリオID列>,
    scenario_inputs=<seam-1 で用意した {id: 実シナリオ入力}>,
    session_id="<一意の開封セッションID>",
    issued_ts=<float>, revoked_ts=<float>,   # 手順4の窓条件を満たす
    weak_items=WEAK, strong_items=STRONG,
    delta_strong=0.02,               # U5b（暫定）
    params=trained,                  # 手順5-0 の学習済み params（省略/None で未学習の既定・後方互換）
)
```

`run_sealed_evaluation` が内部で:
1. `open_eval_session`（**唯一の正規開封経路**・aggregate 強制・生涯計数を消費＋永続化）で**1回だけ開封**、
2. 全 GT を**単一トークン下**で read、
3. supreme を実走（seam-1 アダプタ → `core.run_supreme(snaps, params=trained)`＝**学習済みで採点**）して `harness.canonical_metric_spec()` で採点、
4. baseline を `load_baseline_scores`（同一 8層 schema・不一致は `BaselineSchemaMismatch`）、
5. `compare_items` で項目別 verdict、
6. `revoke_open_token` で失効（評価フェーズを閉じる）。

> **封印は学習に使わない**: 手順5-0 の `fit_supreme` は練習データのみで学習し、手順5-1 の封印開封は評価専用（学習済み params で実走するだけ）。封印 GT を学習に流す経路は存在しない（過学習ガード・ADR 0025 決定3）。

## 6. 検証（実走直後）

```python
assert report.lifetime_session_count == 1     # 生涯開封1回
assert report.audit_passed                    # access_log × audit_seal_access 合格（単一session・窓内）
print(report.comparison.verdicts)             # 項目別: win/lose/draw（弱）・maintained/degraded（強）・no_data
print("success_goal:", report.comparison.success_goal)   # 弱5↑∧強維持（成功目標・合否ゲートではない）
```

プロセス跨ぎの最終保証は、別インスタンスで `store.access_log()` を読み戻し `guard.audit_seal_access(log, report.token)` が合格することで担保（GUARD_IF §3 運用規約2）。

## 7. 結果の解釈（合否ゲートでないことに注意）

- **弱い5項目**: `supreme − baseline > δ_strong` → win ／ `< −δ_strong` → lose ／ `|Δ| ≤ δ_strong` → draw（引き分け）。
- **強い3項目**: 低下が δ_strong 以内 → maintained ／ 超 → degraded。
- 「**弱い5↑ ∧ 強い維持**」は **成功目標**であって合否ゲートではない（SPEC 非機能要件）。未達でも例外は出ない。
- 封印に当該層データが無い項目は `no_data`（勝敗から除外・draw と混同しない）。

## 8. 既知の限界（受容済み・解釈時に留意）

- **統計的有意性なし（U11・穴1）**: 少数封印の勝敗は**点推定**。「勝った」に信頼区間は付かない。
- **封印保全はログ経由検査（穴8）**: ログを介さないアクセス（ファイル直読み等）は検出不能（技術ロック未設計）。
- **本番封印は焼き切り**: 実走後は再開封不可（`production=True` の2回目は `SessionLimitExceeded`）。コード変更後の再評価は新しい封印が要る（穴2）。

## 9. 実走後のフォロー（チューニングの研究ループ）

δ_strong 実測（本実走の項目別差）を起点に、`core.py` 先頭の学習値・観測式・HGF 係数を調整する研究ループは**本実走の測定が前提**（HANDOVER §7）。これは本 runbook の外（実測後の改良サイクル）。
