# situations_v1 能力評価（supreme8 / F-015）— 2026-07-22

world-first 生成の situations_v1（std/emg/crw/bst/dcp/crp・各 train80/eval40）で supreme8（NeuPSL エンジン）を評価した報告。**strict OFF 必須**（ADR 0049/0050）で実走し、契約違反入力は engine 実行前に明示拒否（rejection_acc）した。`src/supreme/*.py` は無変更（アダプタ規約=ADR 0058）。

> ⚠️ **coverage 系スコアと直接比較しない（別土俵）**。引用は必ず 「suite＋split＋測定日（2026-07-22）」を併記すること（README §6）。

## メタ

- 測定日: **2026-07-22** / strict_gt_conformance: **False**
- データ root: `C:\work\_audit-harness-retrofit\otokankyo-scenario-contract\scenarios\situations_v1`
- データ repo HEAD: `079e430952cdf3f5b784dd2adecd6b7a43ef5462`
- エンジン repo HEAD: `68d6f8eb91751021453b21fa8797804e292e1aa2`
- 列挙: train 480（違反 13）/ eval 240（違反 5）。非違反 eval 235 本を採点。

## 構成

- **N1**: params=None(事前重みベースライン=NeuPSL 既定 + t3/scene 既定)
- **N2**: core.fit_supreme(train_all)(既定 10 エポック T2・bilevel なし)
- **N3**: ADR 0057 レシピ(PRIMARY): t3/scene=core.fit_supreme(train_all)、T2=基礎6(neupsl.fit)+bilevel2(neupsl.fit_bilevel・MLP凍結)、dataclasses.replace で T2 差替
- **N3-std**: N3 と同レシピを std/train(80本)だけで学習(生成器スモークと可比)

## rejection_acc（EVALUATION.md §7・明示拒否＝preflight が契約違反を検出）

- **eval 側（公式）**: 5/5 = **1.0000**  内訳 {'frame_count_mismatch': 2, 'bad_version': 1, 'ts_regression': 1, 'type_break': 1}
- train 側（情報）: 13/13 = 1.0000  内訳 {'bad_version': 5, 'ts_regression': 4, 'type_break': 2, 'frame_count_mismatch': 2}

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

## pooled 8 層 global acc（eval・非違反 235 本・strict OFF・2026-07-22）

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

## per-suite overall（eval・非違反）

| suite | N1 | N2 | N3 | N3-std |
|---|:--:|:--:|:--:|:--:|
| std | 0.5602 | 0.6565 | 0.6866 | 0.7782 |
| emg | 0.5503 | 0.5838 | 0.5730 | 0.5547 |
| crw | 0.5232 | 0.7105 | 0.7426 | 0.6022 |
| bst | 0.6471 | 0.6206 | 0.6045 | 0.6878 |
| dcp | 0.5870 | 0.5366 | 0.5472 | 0.5938 |
| crp | 0.4629 | 0.5731 | 0.5921 | 0.5643 |

### N1 — per-suite × per-layer acc

| suite | risk_tier | t1_state | t2_mode | t2_role | t2_relation | t3_hypothesis | quality_regime | scene_regime | overall |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| std | 0.7631 | 0.7276 | 0.3321 | 0.2201 | 0.1884 | 0.3955 | 1.0000 | 0.8545 | 0.5602 |
| emg | 0.3426 | 0.8375 | 0.4305 | 0.8463 | 0.4056 | 0.4436 | 0.9502 | 0.1464 | 0.5503 |
| crw | 0.8481 | 0.8132 | 0.1546 | 0.1492 | 0.4220 | 0.2097 | 1.0000 | 0.5887 | 0.5232 |
| bst | 0.8253 | 0.8806 | 0.5291 | 0.7818 | 0.1757 | 0.5726 | 0.9980 | 0.4136 | 0.6471 |
| dcp | 0.7140 | 0.8759 | 0.5558 | 0.0270 | 0.0324 | 0.6223 | 1.0000 | 0.8687 | 0.5870 |
| crp | 0.6438 | 0.7238 | 0.3029 | 0.5314 | 0.2800 | 0.3867 | 0.7886 | 0.0457 | 0.4629 |

### N2 — per-suite × per-layer acc

| suite | risk_tier | t1_state | t2_mode | t2_role | t2_relation | t3_hypothesis | quality_regime | scene_regime | overall |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| std | 0.7631 | 0.7276 | 0.1660 | 0.8396 | 0.5672 | 0.3340 | 1.0000 | 0.8545 | 0.6565 |
| emg | 0.3426 | 0.8375 | 0.3309 | 0.9502 | 0.7350 | 0.3777 | 0.9502 | 0.1464 | 0.5838 |
| crw | 0.8481 | 0.8132 | 0.6196 | 0.8602 | 0.3239 | 0.6304 | 1.0000 | 0.5887 | 0.7105 |
| bst | 0.8253 | 0.8806 | 0.2103 | 0.5538 | 0.7710 | 0.3119 | 0.9980 | 0.4136 | 0.6206 |
| dcp | 0.7140 | 0.8759 | 0.0000 | 0.2320 | 0.6025 | 0.0000 | 1.0000 | 0.8687 | 0.5366 |
| crp | 0.6438 | 0.7238 | 0.4381 | 0.8533 | 0.6629 | 0.3695 | 0.7886 | 0.1048 | 0.5731 |

### N3 — per-suite × per-layer acc

| suite | risk_tier | t1_state | t2_mode | t2_role | t2_relation | t3_hypothesis | quality_regime | scene_regime | overall |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| std | 0.7631 | 0.7276 | 0.2239 | 0.8582 | 0.6567 | 0.4086 | 1.0000 | 0.8545 | 0.6866 |
| emg | 0.3426 | 0.8375 | 0.3616 | 0.9019 | 0.6545 | 0.3895 | 0.9502 | 0.1464 | 0.5730 |
| crw | 0.8481 | 0.8132 | 0.6169 | 0.8602 | 0.5497 | 0.6640 | 1.0000 | 0.5887 | 0.7426 |
| bst | 0.8253 | 0.8806 | 0.2024 | 0.5538 | 0.7710 | 0.1915 | 0.9980 | 0.4136 | 0.6045 |
| dcp | 0.7140 | 0.8759 | 0.0845 | 0.2320 | 0.6025 | 0.0000 | 1.0000 | 0.8687 | 0.5472 |
| crp | 0.6438 | 0.7238 | 0.4724 | 0.8533 | 0.6629 | 0.4876 | 0.7886 | 0.1048 | 0.5921 |

### N3-std — per-suite × per-layer acc

| suite | risk_tier | t1_state | t2_mode | t2_role | t2_relation | t3_hypothesis | quality_regime | scene_regime | overall |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| std | 0.7631 | 0.7276 | 0.5989 | 0.9478 | 0.8340 | 0.5000 | 1.0000 | 0.8545 | 0.7782 |
| emg | 0.3426 | 0.8375 | 0.4100 | 0.9502 | 0.3909 | 0.4100 | 0.9502 | 0.1464 | 0.5547 |
| crw | 0.8481 | 0.8132 | 0.1626 | 0.8495 | 0.2702 | 0.2849 | 1.0000 | 0.5887 | 0.6022 |
| bst | 0.8253 | 0.8806 | 0.6130 | 0.5528 | 0.7512 | 0.4679 | 0.9980 | 0.4136 | 0.6878 |
| dcp | 0.7140 | 0.8759 | 0.1601 | 0.5791 | 0.3921 | 0.1601 | 1.0000 | 0.8687 | 0.5938 |
| crp | 0.6438 | 0.7238 | 0.3162 | 0.8533 | 0.6895 | 0.4381 | 0.7886 | 0.0610 | 0.5643 |

## T2 手配線の ≥ガード（学習 vs 事前重み・最大400練習シナリオ）

- N3: 学習 acc=0.5467 / 事前 acc=0.3769 → 採用=tuned(base6+bilevel2)
- N3-std: 学習 acc=0.7808 / 事前 acc=0.2386 → 採用=tuned(base6+bilevel2)

## timings（秒・metadata・決定性採点には非関与）

| config | train scen | fit s | eval s | crashes | det.identical |
|---|:--:|:--:|:--:|:--:|:--:|
| N1 | 0 | 0.0000 | 38.8133 | 0 | True |
| N2 | 467 | 2250.5268 | 109.6698 | 0 | True |
| N3 | 467 | 2774.1042 | 178.4339 | 0 | True |
| N3-std | 80 | 336.8362 | 94.5417 | 0 | True |

## crash incidents（堅牢性の所見・採点分母には非算入）

- **0 件**（全 config で非違反 235 本が例外なく実走）。

## 正直な注記

- **relation の語彙ギャップ**: departing/unrelated が relation ラベルの約 48% を占め、現特徴（t1_depart・距離）では分離が不十分（ADR 0057 の既知挙動でありバグではない）。
- **dcp/crp の設計意図**: dcp は「観測が嘘をつく」罠（media 音の role は source_object・risk 不上昇）、crp は破損下の Safety Latch。低めの値は設計意図で天井は構造的に 1.0 未満（README §0/§6）。
- **coverage 比較禁止**: 本スイートは world-first 土俵。coverage_v3 の 0.6879 等と同一スケールで比較しない。
- **モチーフ有限性**: train/eval は同一 50 モチーフの別パラメタ。最終確定（seal）には完全新作モチーフが必要（README §10）。能力主張には独立ラベラ照合の併記が要る。

---

生成元: `run_supreme_situations.py` → `results.json` → `make_report.py`。数値は results.json を機械転記。
