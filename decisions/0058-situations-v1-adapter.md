# ADR 0058-s8: situations_v1 対応 — ローダ・preflight 明示拒否・能力評価アダプタ

- 状態: 採用 / 日付: 2026-07-22 / 基点: supreme8 @ feat/situations-v1-eval（master + feature/audit-harness マージ）
- 対象機能: SPEC.md **F-015**
- 根拠: world-first 生成の能力評価スイート **situations_v1**（otokankyo-scenario-contract
  `scenarios/situations_v1`・std/emg/crw/bst/dcp/crp × train80/eval40 = 720 本）で supreme8
  （NeuPSL エンジン）を測る。coverage 系の観測層 GT が生成規則 f の写しで循環得点する問題
  （ADR 0049 撤回）を、GT を潜在世界 W から直接導出することで構造的に排除した「別土俵」。

## 決定

### 1. アダプタ規約（core.py 無変更）
situations_v1 対応は **`src/supreme/*.py` を一切変更せず**、キャンペーンディレクトリ
`reports/situations_v1-eval-20260722/` に importable な純ロジック（`situations_common.py`）と
ランナー（`run_supreme_situations.py`）として置く。理由:
- core.py は ADR 0050 の strict ゲート・多数の回帰テストの規律下にあり、評価アダプタの都合で
  触るべきでない（F-013 seal 評価が確立した「core 無変更・アダプタ規約」を踏襲）。
- 契約検証（preflight）はエンジンの入力検証（`core._validate_snapshot`）より広い（フレーム数
  一致・tracks 型は core が見ない／見られない）。これは能力評価アダプタ側の責務であり、
  core に混ぜると通常経路の後方互換を壊す。
- 歴史的 seal ローダの絶対パス腐り（scratchpad ハードコード）を避け、ランナーは自身位置からの
  相対（`os.path.join(os.path.dirname(__file__), "..", "..", "src")`）で src を解決する。

### 2. preflight 契約検証（engine 実行**前**の明示拒否）
`preflight_validate(pso_frames, gt_frame_count)` が固定順・決定的に検査し、構造化 verdict
（`ok` / `reason` ∈ {bad_version, ts_regression, frame_count_mismatch, type_break, other}）を返す:
1. **bad_version**: version が `PSO-Snapshot/` 始まりでない（**書き換えず**判定）。
2. **ts_regression**: ts の単調非減少違反（後退）。
3. **type_break**: tracks が dict でない／tracks.audio・humans・objects が存在するのに list でない・
   要素が dict でない（現状 core はこれを検査せず、深部で AttributeError になる）。
4. **frame_count_mismatch**: PSO 行数 ≠ GT フレーム数。

**version は決して書き換えない**: 歴史的 seal ローダは `s["version"]="PSO-Snapshot/1.4"` で強制上書き
していたが、situations_v1 でこれをやると bad_version 違反を洗浄してしまう（拒否できなくなる）。
situations_v1 は正規の 1.4 フル形なので origin/version の補完は不要（README §8）。非違反シナリオの
geom 欠落（ttc_blackout 等の破損仕様=degrade であって違反でない）だけ min_TTC_s=999.0 で補完する
（seal/cv3 の慣習に一致。engine 既定フォールバックは 99.0 だが、過去キャンペーンと整合させる）。

### 3. 採点規約（違反除外＋rejection_acc・per-suite＋pooled）
- 契約違反（`corruption.contract_violation: true`・全 18 本 crp）を 8 層採点の全分母から**除外**し、
  rejection_acc =（preflight 明示拒否の違反本数）/（違反総本数）で別採点（EVALUATION.md §7）。
  eval 側 5 本を公式、train 側 13 本を情報として別掲。
- 非違反 eval は `config={"strict_gt_conformance": False}` で engine 実走し、生 GT（ラベル形）を
  index 対応で突合して `harness.score`（F-004・無変更）で per-suite・pooled を採点。
- 非違反シナリオで engine が例外を出したら握り潰さず incident（sid+トレースバック要約）として記録し
  件数を明示（採点分母には算入せず=全フレーム誤りとは扱わない。堅牢性の所見として別掲）。

### 4. strict OFF 必須（ADR 0049/0050）
能力評価の実走は必ず `config={"strict_gt_conformance": False}`。strict ON（既定）は gt_derive 系
規則の写し（ADR 0043〜0048）を view に適用し循環スコアを再生するため能力評価では使わない。
strict OFF は T2 を NeuPSL 結合 MAP 経路（`_run_one_scenario_neupsl`）に通す。

### 5. 学習レシピの手配線（fit_bilevel が core から未配線である事実）
`core.fit_supreme` は t3/scene を学習し、T2 を `neupsl.fit(epochs=10)` で学習するが、
**`neupsl.fit_bilevel` を呼ばない**。ADR 0057 の最良レシピ（8層平均 0.6879）である「基礎 6 エポック
＋ bilevel 2 エポック」は、リポジトリに残っていない一回性スクリプトで手配線されていた。本キャンペーンは
これを再現するため 4 構成を測る:
- **N1**: params=None（事前重みベースライン=NeuPSL 既定 + t3/scene 既定）。
- **N2**: `core.fit_supreme(train_all)`（既定 10 エポック T2・bilevel なし）。
- **N3（PRIMARY）**: t3/scene は N2 と同一の `core.fit_supreme(train_all)` を共有し、T2 のみ手配線で
  `neupsl.fit(epochs=6)` → `neupsl.fit_bilevel(epochs=2, rho=0.6, mu=1.0, lr_y=0.2, lr_w=0.08, lr_n=0.0)`
  （MLP 凍結=lr_n=0・ADR 0054 の保守設定）。T2 学習入力 `t2_scens` は `core.fit_supreme` の本体
  （core.py:1611-1622）と同一手順（`core._neupsl_inputs_from_scenario` + GT ラベル）で構築し、
  ≥ガード（最大 400 練習シナリオで学習 vs 既定=事前重みを比較し良い方 >=）も core と同一に適用。
  `dataclasses.replace(base, t2=t2_chosen)` で SupremeParams に差し替え。
- **N3-std**: N3 と同レシピを std/train（80 本・違反なし）だけで学習（生成器スモーク参照値と可比）。

学習データ = 各 suite の train split から契約違反 13 本を除外（N3-std は std/train のみ=違反ゼロ）。
N2 の params と N3 の t3/scene 源は同一の `core.fit_supreme(train_all)` 呼び出しを共有し二重学習を避ける。

## 検証（situations_v1・eval split・strict OFF・測定日 2026-07-22）

- データ repo HEAD: `079e430952cdf3f5b784dd2adecd6b7a43ef5462`
  （otokankyo-scenario-contract @ nsepi-corpus/situations-v1-physics）。
- エンジン repo HEAD: `68d6f8eb91751021453b21fa8797804e292e1aa2`（supreme8 @ feat/situations-v1-eval）。
- 列挙: train 480（違反 13）/ eval 240（違反 5）。非違反 eval 235 本（4,057 フレーム）を採点。
- **coverage 系スコアと同一土俵で比較しない**（別土俵）。引用は suite+split+測定日を併記。

### rejection_acc（EVALUATION.md §7）

- **eval 側（公式）**: 5/5 = **1.0000**  内訳 {frame_count_mismatch: 2, bad_version: 1, ts_regression: 1, type_break: 1}
- train 側（情報）: 13/13 = 1.0000  内訳 {bad_version: 5, ts_regression: 4, type_break: 2, frame_count_mismatch: 2}

| split | sid | rejected | reason |
|---|---|:--:|---|
| eval | crp-violation-eval-02 | ✓ | frame_count_mismatch |
| eval | crp-violation-eval-05 | ✓ | bad_version |
| eval | crp-violation-eval-08 | ✓ | ts_regression |
| eval | crp-violation-eval-11 | ✓ | type_break |
| eval | crp-violation-eval-14 | ✓ | frame_count_mismatch |
| train | crp-dropout_approach-train-06 | ✓ | bad_version |
| train | crp-dropout_approach-train-13 | ✓ | bad_version |
| train | crp-frozen_passby-train-07 | ✓ | ts_regression |
| train | crp-violation-train-00 | ✓ | ts_regression |
| train | crp-violation-train-01 | ✓ | bad_version |
| train | crp-violation-train-03 | ✓ | type_break |
| train | crp-violation-train-04 | ✓ | ts_regression |
| train | crp-violation-train-06 | ✓ | frame_count_mismatch |
| train | crp-violation-train-07 | ✓ | type_break |
| train | crp-violation-train-09 | ✓ | bad_version |
| train | crp-violation-train-10 | ✓ | frame_count_mismatch |
| train | crp-violation-train-12 | ✓ | ts_regression |
| train | crp-violation-train-13 | ✓ | bad_version |

### pooled 8 層平均（eval・非違反 235 本）

| layer | N1 | N2 | N3 | N3-std |
|---|:--:|:--:|:--:|:--:|
| risk_tier | 0.7013 | 0.7013 | 0.7013 | 0.7013 |
| t1_state | 0.8198 | 0.8198 | 0.8198 | 0.8198 |
| t2_mode | 0.3922 | 0.3005 | 0.3268 | 0.3939 |
| t2_role | 0.4666 | 0.7091 | 0.7035 | 0.7688 |
| t2_relation | 0.2551 | 0.6189 | 0.6586 | 0.5561 |
| t3_hypothesis | 0.4437 | 0.3490 | 0.3522 | 0.3828 |
| quality_regime | 0.9638 | 0.9638 | 0.9638 | 0.9638 |
| scene_regime | 0.4737 | 0.4814 | 0.4814 | 0.4757 |
| **8層平均** | **0.5645** | **0.6180** | **0.6259** | **0.6328** |

### per-suite overall（eval・非違反）

| suite | N1 | N2 | N3 | N3-std |
|---|:--:|:--:|:--:|:--:|
| std | 0.5602 | 0.6565 | 0.6866 | 0.7782 |
| emg | 0.5503 | 0.5838 | 0.5730 | 0.5547 |
| crw | 0.5232 | 0.7105 | 0.7426 | 0.6022 |
| bst | 0.6471 | 0.6206 | 0.6045 | 0.6878 |
| dcp | 0.5870 | 0.5366 | 0.5472 | 0.5938 |
| crp | 0.4629 | 0.5731 | 0.5921 | 0.5643 |

### N3（PRIMARY）per-suite × per-layer acc

| suite | risk_tier | t1_state | t2_mode | t2_role | t2_relation | t3_hypothesis | quality_regime | scene_regime | overall |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| std | 0.7631 | 0.7276 | 0.2239 | 0.8582 | 0.6567 | 0.4086 | 1.0000 | 0.8545 | 0.6866 |
| emg | 0.3426 | 0.8375 | 0.3616 | 0.9019 | 0.6545 | 0.3895 | 0.9502 | 0.1464 | 0.5730 |
| crw | 0.8481 | 0.8132 | 0.6169 | 0.8602 | 0.5497 | 0.6640 | 1.0000 | 0.5887 | 0.7426 |
| bst | 0.8253 | 0.8806 | 0.2024 | 0.5538 | 0.7710 | 0.1915 | 0.9980 | 0.4136 | 0.6045 |
| dcp | 0.7140 | 0.8759 | 0.0845 | 0.2320 | 0.6025 | 0.0000 | 1.0000 | 0.8687 | 0.5472 |
| crp | 0.6438 | 0.7238 | 0.4724 | 0.8533 | 0.6629 | 0.4876 | 0.7886 | 0.1048 | 0.5921 |

### timings（秒・metadata・決定性採点には非関与）

| config | train scen | fit s | eval s | crashes | det.identical |
|---|:--:|:--:|:--:|:--:|:--:|
| N1 | 0 | 0.0000 | 38.8133 | 0 | True |
| N2 | 467 | 2250.5268 | 109.6698 | 0 | True |
| N3 | 467 | 2774.1042 | 178.4339 | 0 | True |
| N3-std | 80 | 336.8362 | 94.5417 | 0 | True |

### 決定性・堅牢性
- 決定性: 各 config で std/eval 先頭 5 本を 2 回実走し view 完全一致を確認（各 config で 5 sid、計 20 sid を確認し、全 config で `identical=True`）。
- crash incidents: 全 config 合計 **0 件**。

## 正直な注記
- **relation の語彙ギャップ**: departing/unrelated が relation ラベルの約 48% を占めるが、現特徴
  （t1_depart・距離）では分離が不十分（ADR 0057 の既知挙動であってバグではない）。回収には新述語
  向けの特徴拡充が前提。
- **dcp/crp の設計意図**: dcp は「観測が嘘をつく」罠（media 再生音の role は source_object・risk 不上昇）、
  crp は破損下の Safety Latch。低めの値は設計意図であり、天井は構造的に 1.0 未満（README §0/§6）。
- **モチーフ有限性**: train/eval は同一 50 モチーフの別パラメタ。最終確定測定（seal）には完全新作
  モチーフが必要（生成器側の宿題・README §10）。能力主張には独立ラベラ（f_blind）照合の併記が要る。
- **既存テスト失敗（F-015と無関係）**: `tests/test_Phase1_learning_wiring.py` の F-014-1 ガード
  （param_count=362 ≥ 360）が master 基点で既に失敗している（ADR 0057 の新ルールでパラメータが
  353→362に増えたことによる閾値超過。F-015 の全変更を退避した状態で再現確認済み）。F-015 のテスト
  自体は全緑（新規追加分含む 890 passed）。
