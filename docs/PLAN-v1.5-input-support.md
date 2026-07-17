# 実装計画: supreme を NS-EPI Input Contract **v1.5** 入力対応へ

> **⚠️ 撤回注記（2026-06-26・ADR 0049）**: 本書中の「8層平均 0.6305」等の rule_derived 層スコアは能力指標として
> 撤回済み（GT 生成規則の写しによる循環）。回帰不変（regression）の基準値としての利用は引き続き有効だが、
> 能力・優劣の文脈では引用しないこと。詳細: `decisions/0049-evaluation-contamination-retraction.md`。

対象: `N04-scenario-contract` の **v1.5**（`contracts/ns_epi_input_contract_v_1.5.md`）が追加した観測コンテキストを
supreme が消費し、t3 / scene / role の天井に近づく。ROADMAP Track C の supreme 側実装。

## 0. 原則（必読）

- **後方互換ゲート（presence-gated）**: v1.5 追加フィールドは**任意**。`episode`/`scene_state.stability`/track の
  `salience,subtype` が**在れば使う・無ければ現行 v1.4 挙動**。これで coverage_v1 / v021_core / 現 seal の
  **スコア（8層平均 0.6305）と全800テストを不変**に保つ（回帰ゼロが受け入れの絶対条件）。
- **2 段階**: coverage_v2 はまだ無い。
  - **Phase A（今すぐ可）**: v1.5-aware コードを実装＋**合成 v1.5 フレーム**で unit テスト。gain は測れないが
    「正しさ」と「後方互換」を担保。
  - **Phase B（coverage_v2 到着後）**: train で fit・**新 seal** で acc 測定・**アブレーション**で gain と非循環有効性を検証。
- **規律**: train 開発・新 seal 検証のみ・**seal 合わせ込み禁止**・テストは契約・各トラックに ADR。決定的（乱数/時刻なし）。
- 入力の非循環は契約側が保証（観測 proxy）。supreme は**消費するだけ**。

## 1. Phase 0 — 入力プラミング（共通基盤）

`core.py`:
- **version 受理拡張**: gate（`_SNAPSHOT_PREFIX` / §gate `_assert_snapshot`）に `PSO-Snapshot/1.5` を追加（1.3/1.4/1.5 受理）。
- **新ヘルパ（欠落 None・後方互換）**:
  - `_episode(snap)` → `snap.get("episode")`（dict or None）
  - `_stability(snap)` → `(snap.get("scene_state") or {}).get("stability")`（dict or None）
  - per-track `salience`/`subtype`: 既存 `_audio_tracks`/`_human_tracks`/`_object_tracks` の各要素から `.get("salience")`/`.get("subtype")`
- テスト: `test_F0XX_v15_parsing` — 欠落で None・存在でパース・version 1.5 受理。

## 2. 層別実装（3 トラック・依存順）

### T-Role（C-1c）— salience/subtype → 6 クラス role  ★最も明確
- 現状: `role.py` の `SOURCE_HUMAN`/`SOURCE_OBJECT` は定数のみ（発火ルール無し＝0 固定）。`core._role_evidence` は audio 中心。
- 変更:
  - `core._role_evidence`: `salience` が在るとき、**salience 最大の track** とその category/subtype を証拠に追加（presence-gated）。
  - `role.py`: salience 駆動の発火を追加 — **緊急音優先（siren/alarm→source_alarm・ADR 0033 の tie-break 維持）** →
    それ以外は argmax salience の category（audio speech→source_speech / vehicle→source_vehicle /
    human→**source_human** / 非 vehicle object→**source_object** / 無→unknown）。`salience` 不在時は**現行4クラス規則**。
  - `_LABEL_ORDER` は既に 6 ラベル。出力契約も 6 クラスで変更不要。
- テスト: 合成 v1.5（human が salience 最大）→ source_human / object→source_object。v1.4 フレームで現行不変。
- 期待: role の source_human/object **0→可**・全体 role↑。**実装が最も独立で先行着手に適**。

### T-Scene（C-1b）— stability → scene_regime
- 現状: `scene.py`（F-010・HGF 学習）は scene 診断信号列を入力に regime 3 クラス。診断抽出は core 側。
- 変更:
  - `core` の scene 診断信号生成に **stability 由来特徴**を追加（presence-gated）: `qos_trend<0 ∧ noise_trend>0`→DEGRADING 方向、
    `track_churn` 高 ∨ `change_point` 直近→CHANGING 方向。
  - `scene.py`: 学習層（HGF param + regime 閾値）の入力に stability 特徴を加える（学習可能 param 拡張・`fit_supreme` で学習）。
    不在時は現行 health_raw のみ。
- テスト: 合成で stability が regime を動かす・v1.4 不変。
- 期待: scene 0.52 →（天井 0.77 方向）。学習層なので `fit_supreme` の param 予算（`guard.check_param_budget`）内を確認。

### T-T3（C-1a）— episode → t3_hypothesis  ★最高価値・要注意
- 現状: `t3.py` は `mode_window`（モデル mode 履歴）依存＝ボトルネック。ADR 0033 で「会話×衝突危険」フレームが
  mode=emergency になり t3=conv_participating を復元できず LOSE。
- 変更:
  - `core`/`t3.episode_features`: **episode 由来特徴**（`speech_ratio`/`turn_count`/`hazard_trend`/`approach_ratio`）を追加（presence-gated）。
  - `t3.py`: 会話継続（`speech_ratio` 高 ∧ `turn_count≥k`）なら mode=emergency でも **conv_participating を保持**する規則/学習を
    `_rule_hypothesis` か学習層に配線。`hazard_trend` 持続→sustained_alert/traffic 方向。
  - `fit_supreme`: t3 学習 param に episode 特徴を追加して学習。
- テスト: 会話×危険フレームで conv_participating・v1.4 不変。
- 期待: t3 −0.078 → 改善（ADR 0033 副作用の解消が一次目標）。**mode→t3 の相互作用に注意**（episode は mode を上書きでなく補完）。

## 3. 横断・非機能

- **後方互換の保証**: 全変更を presence-gate。**回帰テスト**で v1.4 データ（coverage_v1/v021）の 800 テスト緑＋
  seal 0.6305 不変を CI 化（gain 追求より先に「壊さない」を固定）。
- **fit_supreme**: scene/t3 の学習 param 拡張。`guard.check_param_budget` 予算内・決定性維持。role は規則（学習不要）。
- **ADR**: 0034（role v1.5）/ 0035（scene v1.5）/ 0036（t3 v1.5）。各トラックで test-writer→implementer→auditor。

## 4. Phase B — 検証（coverage_v2 到着後）

1. `train`（coverage_v2）で `fit_supreme`。**新 seal** で role/scene/t3 acc を測定。
2. **アブレーション**: 各 v1.5 信号を定数化して該当層 acc が**落ちる**ことを確認（落ちなければ wiring が効いていない）。
3. 受け入れ: 新 seal で role/scene/t3 改善・**v1.4 seal（0.6305）不変**・契約側の heuristic_confirmed 上昇と整合。
4. **seal 合わせ込み禁止**（develop=train/new-eval）。

## 5. 順序・リスク・期待

| 順 | 作業 | リスク | 期待 |
|---|---|---|---|
| 1 | Phase 0 入力プラミング | 低 | 基盤 |
| 2 | T-Role | 低（独立・即テスト） | role source_human/object 0→可 |
| 3 | T-Scene | 中（学習層） | scene 0.52→天井方向 |
| 4 | T-T3 | 中〜高（mode↔t3） | t3 −0.078→改善（ADR 0033 解消） |
| 5 | Phase B 検証 | coverage_v2 依存 | gain 確定 |

- **最大のリスク**: gain の確定は **coverage_v2 待ち**。Phase A で測れるのは「正しさ＋後方互換」のみ（誠実に明記）。
- **過適合**: Phase B は新 seal＋アブレーションで防ぐ。**v1.4 回帰**は presence-gate＋回帰テストで防ぐ。
- **やらないこと**: 既存 seal/coverage の GT への合わせ込み（ROADMAP「やらないこと」と一致）。

---
*関連: 契約 `N04-scenario-contract/contracts/ns_epi_input_contract_v_1.5.md`、`ROADMAP.md`、
`coverage_v1/README.md`（seal の使い方）。本計画は Phase A から着手可能（coverage_v2 非依存）。*
