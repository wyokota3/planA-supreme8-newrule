# 弱3層 誤り診断レポート — t3_hypothesis / scene_regime / quality_regime

- 生成時刻: 2026-06-14 17:24
- 対象シナリオ: 20 件
- 経路: run_dev_eval と同一(PSO→core.run_supreme→v1.4 view、GT→ADR0006 正準化→v1.4 gt view)
- 正準化・データ対応ロジックは `run_dev_eval.py` を再利用(二重実装なし)
- supreme 本体・テストは未変更(診断のみ)。baseline は import していない。決定的。

> 注: これは in-sample(v021_core)診断。最終 verdict ではなく構造原因の切り分けが目的。

## 結論サマリ(各層の切り分け)

| 層 | acc | GT語彙数 | supreme出力語彙数 | 混同の型 | 判定 |
|---|---:|---:|---:|---|---|
| t3_hypothesis | 0.3286 | 10 | 3 | 分散(最頻 'traffic_unstable' 53%) | (A) 語彙/配線の構造ミス寄り |
| scene_regime | 0.3238 | 3 | 2 | 定数潰れ('CHANGING'へ 97%) | (A) 語彙/配線の構造ミス寄り |
| quality_regime | 0.4762 | 3 | 3 | 特定クラス偏り('DEGRADED'へ 64%) | (B) 係数の未チューニング寄り |

## t3_hypothesis

- 採点フレーム数(GT 非 null): 210 / 正答 69 → acc = **0.3286**

### 1. 語彙集合の対照(構造ミス検出)

**GT 側に出現する v1.4 ラベル集合と頻度:**

| GT ラベル | 頻度 |
|---|---:|
| `quiet_stable` | 84 |
| `conv_participating` | 29 |
| `traffic_unstable` | 23 |
| `sustained_alert` | 23 |
| `env_shift` | 15 |
| `crowd_tendency` | 14 |
| `uncertain_context` | 9 |
| `env_start` | 7 |
| `alert_required` | 4 |
| `hazard_declining` | 2 |

**supreme 側が出力する v1.4 ラベル集合と頻度(GT 採点対象フレーム上):**

| supreme ラベル | 頻度 |
|---|---:|
| `traffic_unstable` | 111 |
| `quiet_stable` | 94 |
| `conv_participating` | 5 |

**集合の食い違い:**

- ⚠️ GT に出るが supreme が **一度も出さない**ラベル: `alert_required`(×4), `crowd_tendency`(×14), `env_shift`(×15), `env_start`(×7), `hazard_declining`(×2), `sustained_alert`(×23), `uncertain_context`(×9)
- supreme が出すが GT に無いラベル: なし
- 共有ラベル: ['conv_participating', 'quiet_stable', 'traffic_unstable']
- supreme 出力は supreme v1.4 語彙集合 ['alert_required', 'conv_participating', 'crowd_tendency', 'env_shift', 'env_start', 'hazard_declining', 'quiet_stable', 'sustained_alert', 'traffic_unstable', 'uncertain_context'] に収束(配線健全)

### 2. 混同行列(GT 行 → supreme 予測 列)

| GT＼予測 | `conv_participating` | `quiet_stable` | `traffic_unstable` | 行計 |
|---|---:|---:|---:|---:|
| `alert_required` | · | · | 4 | 4 |
| `conv_participating` | **5** | 5 | 19 | 29 |
| `crowd_tendency` | · | 12 | 2 | 14 |
| `env_shift` | · | 9 | 6 | 15 |
| `env_start` | · | 4 | 3 | 7 |
| `hazard_declining` | · | · | 2 | 2 |
| `quiet_stable` | · | **50** | 34 | 84 |
| `sustained_alert` | · | 4 | 19 | 23 |
| `traffic_unstable` | · | 9 | **14** | 23 |
| `uncertain_context` | · | 1 | 8 | 9 |

### 3. シナリオ別精度(20 シナリオ)

| dir | scenario_id | 採点数 | 正答 | acc |
|---|---|---:|---:|---:|
| ns001_boot_sanity | ns-epi-v021-ns001-boot-sanity | 3 | 3 | 1.000 |
| ns002_conv_approach | ns-epi-v021-ns002-conv-approach | 6 | 0 | 0.000 ⚠️ |
| ns003_siren_danger | ns-epi-v021-ns003-siren-danger | 5 | 0 | 0.000 ⚠️ |
| ns004_input_degradation | ns-epi-v021-ns004-input-degradation | 5 | 0 | 0.000 ⚠️ |
| ns005_anomaly_surprise | ns-epi-v021-ns005-anomaly-surprise | 6 | 2 | 0.333 |
| ns006_scene_transition | ns-epi-v021-ns006-scene-transition | 6 | 0 | 0.000 ⚠️ |
| ns007_crowd_ambient | ns-epi-v021-ns007-crowd-ambient | 5 | 0 | 0.000 ⚠️ |
| ns008_vehicle_caution | ns-epi-v021-ns008-vehicle-caution | 5 | 4 | 0.800 |
| ns009_quality_recovery | ns-epi-v021-ns009-quality-recovery | 7 | 1 | 0.143 |
| ns010_long_idle | ns-epi-v021-ns010-long-idle | 8 | 8 | 1.000 |
| ns011_multi_stress | ns-epi-v021-ns011-multi-stress | 6 | 1 | 0.167 |
| ns012_vehicle_pass | ns-epi-v021-ns012-vehicle-pass | 7 | 1 | 0.143 |
| ns013_scene_degrading | ns-epi-v021-ns013-scene-degrading | 8 | 3 | 0.375 |
| ns014_quality_safety_latch | ns-epi-v021-ns014-quality-safety-latch | 5 | 0 | 0.000 ⚠️ |
| ns015_full_coverage | ns-epi-v021-ns015-full-coverage | 20 | 6 | 0.300 |
| ns016_deep_conversation | ns-epi-v021-ns016-deep-conversation | 24 | 7 | 0.292 |
| ns017_vehicle_lifecycle | ns-epi-v021-ns017-vehicle-lifecycle | 24 | 8 | 0.333 |
| ns018_quality_cycle | ns-epi-v021-ns018-quality-cycle | 20 | 9 | 0.450 |
| ns019_scene_regime_cycle | ns-epi-v021-ns019-scene-regime-cycle | 20 | 10 | 0.500 |
| ns020_sustained_emergency | ns-epi-v021-ns020-sustained-emergency | 20 | 6 | 0.300 |

- **acc=0 の致命的シナリオ**: ['ns-epi-v021-ns002-conv-approach', 'ns-epi-v021-ns003-siren-danger', 'ns-epi-v021-ns004-input-degradation', 'ns-epi-v021-ns006-scene-transition', 'ns-epi-v021-ns007-crowd-ambient', 'ns-epi-v021-ns014-quality-safety-latch']

### 4. 最頻ラベル(定数出力に潰れていないか)

- GT 最頻ラベル: `quiet_stable`（84 / 210 = 40%）
- supreme 予測最頻ラベル: `traffic_unstable`（111 / 210 = 53%）

### 5. 判定(構造ミス A か 未チューニング B か)

**判定: (A) 語彙/配線の構造ミス寄り**

根拠:
- GT にあり supreme が出さないクラス=['alert_required', 'crowd_tendency', 'env_shift', 'env_start', 'hazard_declining', 'sustained_alert', 'uncertain_context'](GT 出現の 35%・部分的)
- supreme は GT 10 クラス中 3 クラスしか出力せず、語彙被覆率 30%(過半クラスを構造的に出せていない= 閾値ズレでは説明困難)

## scene_regime

- 採点フレーム数(GT 非 null): 210 / 正答 68 → acc = **0.3238**

### 1. 語彙集合の対照(構造ミス検出)

**GT 側に出現する v1.4 ラベル集合と頻度:**

| GT ラベル | 頻度 |
|---|---:|
| `STABLE` | 114 |
| `CHANGING` | 66 |
| `DEGRADING` | 30 |

**supreme 側が出力する v1.4 ラベル集合と頻度(GT 採点対象フレーム上):**

| supreme ラベル | 頻度 |
|---|---:|
| `CHANGING` | 203 |
| `DEGRADING` | 7 |

**集合の食い違い:**

- ⚠️ GT に出るが supreme が **一度も出さない**ラベル: `STABLE`(×114)
- supreme が出すが GT に無いラベル: なし
- 共有ラベル: ['CHANGING', 'DEGRADING']
- supreme 出力は supreme v1.4 語彙集合 ['CHANGING', 'DEGRADING', 'STABLE'] に収束(配線健全)

### 2. 混同行列(GT 行 → supreme 予測 列)

| GT＼予測 | `CHANGING` | `DEGRADING` | 行計 |
|---|---:|---:|---:|
| `CHANGING` | **64** | 2 | 66 |
| `DEGRADING` | 26 | **4** | 30 |
| `STABLE` | 113 | 1 | 114 |

### 3. シナリオ別精度(20 シナリオ)

| dir | scenario_id | 採点数 | 正答 | acc |
|---|---|---:|---:|---:|
| ns001_boot_sanity | ns-epi-v021-ns001-boot-sanity | 3 | 0 | 0.000 ⚠️ |
| ns002_conv_approach | ns-epi-v021-ns002-conv-approach | 6 | 0 | 0.000 ⚠️ |
| ns003_siren_danger | ns-epi-v021-ns003-siren-danger | 5 | 3 | 0.600 |
| ns004_input_degradation | ns-epi-v021-ns004-input-degradation | 5 | 0 | 0.000 ⚠️ |
| ns005_anomaly_surprise | ns-epi-v021-ns005-anomaly-surprise | 6 | 2 | 0.333 |
| ns006_scene_transition | ns-epi-v021-ns006-scene-transition | 6 | 3 | 0.500 |
| ns007_crowd_ambient | ns-epi-v021-ns007-crowd-ambient | 5 | 0 | 0.000 ⚠️ |
| ns008_vehicle_caution | ns-epi-v021-ns008-vehicle-caution | 5 | 5 | 1.000 |
| ns009_quality_recovery | ns-epi-v021-ns009-quality-recovery | 7 | 0 | 0.000 ⚠️ |
| ns010_long_idle | ns-epi-v021-ns010-long-idle | 8 | 0 | 0.000 ⚠️ |
| ns011_multi_stress | ns-epi-v021-ns011-multi-stress | 6 | 3 | 0.500 |
| ns012_vehicle_pass | ns-epi-v021-ns012-vehicle-pass | 7 | 6 | 0.857 |
| ns013_scene_degrading | ns-epi-v021-ns013-scene-degrading | 8 | 2 | 0.250 |
| ns014_quality_safety_latch | ns-epi-v021-ns014-quality-safety-latch | 5 | 2 | 0.400 |
| ns015_full_coverage | ns-epi-v021-ns015-full-coverage | 20 | 9 | 0.450 |
| ns016_deep_conversation | ns-epi-v021-ns016-deep-conversation | 24 | 7 | 0.292 |
| ns017_vehicle_lifecycle | ns-epi-v021-ns017-vehicle-lifecycle | 24 | 10 | 0.417 |
| ns018_quality_cycle | ns-epi-v021-ns018-quality-cycle | 20 | 0 | 0.000 ⚠️ |
| ns019_scene_regime_cycle | ns-epi-v021-ns019-scene-regime-cycle | 20 | 8 | 0.400 |
| ns020_sustained_emergency | ns-epi-v021-ns020-sustained-emergency | 20 | 8 | 0.400 |

- **acc=0 の致命的シナリオ**: ['ns-epi-v021-ns001-boot-sanity', 'ns-epi-v021-ns002-conv-approach', 'ns-epi-v021-ns004-input-degradation', 'ns-epi-v021-ns007-crowd-ambient', 'ns-epi-v021-ns009-quality-recovery', 'ns-epi-v021-ns010-long-idle', 'ns-epi-v021-ns018-quality-cycle']

### 4. 最頻ラベル(定数出力に潰れていないか)

- GT 最頻ラベル: `STABLE`（114 / 210 = 54%）
- supreme 予測最頻ラベル: `CHANGING`（203 / 210 = 97%）
- ⚠️ supreme 予測が単一クラスに 97% 集中 = ほぼ定数出力

### 5. 判定(構造ミス A か 未チューニング B か)

**判定: (A) 語彙/配線の構造ミス寄り**

根拠:
- GT 語彙のうち supreme が一度も出さないクラスが GT 出現の 54% を占める(取りこぼし語彙=['STABLE'])
- supreme 予測が単一クラス 'CHANGING' に 97% 集中(定数出力に近い)一方 GT は 3 クラスに分布

## quality_regime

- 採点フレーム数(GT 非 null): 210 / 正答 100 → acc = **0.4762**

### 1. 語彙集合の対照(構造ミス検出)

**GT 側に出現する v1.4 ラベル集合と頻度:**

| GT ラベル | 頻度 |
|---|---:|
| `GOOD` | 154 |
| `DEGRADED` | 32 |
| `BLOCK` | 24 |

**supreme 側が出力する v1.4 ラベル集合と頻度(GT 採点対象フレーム上):**

| supreme ラベル | 頻度 |
|---|---:|
| `DEGRADED` | 134 |
| `GOOD` | 56 |
| `BLOCK` | 20 |

**集合の食い違い:**

- GT に出るが supreme が出さないラベル: なし
- supreme が出すが GT に無いラベル: なし
- 共有ラベル: ['BLOCK', 'DEGRADED', 'GOOD']
- supreme 出力は supreme v1.4 語彙集合 ['BLOCK', 'DEGRADED', 'GOOD'] に収束(配線健全)

### 2. 混同行列(GT 行 → supreme 予測 列)

| GT＼予測 | `BLOCK` | `DEGRADED` | `GOOD` | 行計 |
|---|---:|---:|---:|---:|
| `BLOCK` | **16** | 8 | · | 24 |
| `DEGRADED` | 4 | **28** | · | 32 |
| `GOOD` | · | 98 | **56** | 154 |

### 3. シナリオ別精度(20 シナリオ)

| dir | scenario_id | 採点数 | 正答 | acc |
|---|---|---:|---:|---:|
| ns001_boot_sanity | ns-epi-v021-ns001-boot-sanity | 3 | 0 | 0.000 ⚠️ |
| ns002_conv_approach | ns-epi-v021-ns002-conv-approach | 6 | 0 | 0.000 ⚠️ |
| ns003_siren_danger | ns-epi-v021-ns003-siren-danger | 5 | 2 | 0.400 |
| ns004_input_degradation | ns-epi-v021-ns004-input-degradation | 5 | 4 | 0.800 |
| ns005_anomaly_surprise | ns-epi-v021-ns005-anomaly-surprise | 6 | 1 | 0.167 |
| ns006_scene_transition | ns-epi-v021-ns006-scene-transition | 6 | 1 | 0.167 |
| ns007_crowd_ambient | ns-epi-v021-ns007-crowd-ambient | 5 | 0 | 0.000 ⚠️ |
| ns008_vehicle_caution | ns-epi-v021-ns008-vehicle-caution | 5 | 1 | 0.200 |
| ns009_quality_recovery | ns-epi-v021-ns009-quality-recovery | 7 | 2 | 0.286 |
| ns010_long_idle | ns-epi-v021-ns010-long-idle | 8 | 4 | 0.500 |
| ns011_multi_stress | ns-epi-v021-ns011-multi-stress | 6 | 4 | 0.667 |
| ns012_vehicle_pass | ns-epi-v021-ns012-vehicle-pass | 7 | 4 | 0.571 |
| ns013_scene_degrading | ns-epi-v021-ns013-scene-degrading | 8 | 0 | 0.000 ⚠️ |
| ns014_quality_safety_latch | ns-epi-v021-ns014-quality-safety-latch | 5 | 5 | 1.000 |
| ns015_full_coverage | ns-epi-v021-ns015-full-coverage | 20 | 1 | 0.050 |
| ns016_deep_conversation | ns-epi-v021-ns016-deep-conversation | 24 | 21 | 0.875 |
| ns017_vehicle_lifecycle | ns-epi-v021-ns017-vehicle-lifecycle | 24 | 21 | 0.875 |
| ns018_quality_cycle | ns-epi-v021-ns018-quality-cycle | 20 | 9 | 0.450 |
| ns019_scene_regime_cycle | ns-epi-v021-ns019-scene-regime-cycle | 20 | 7 | 0.350 |
| ns020_sustained_emergency | ns-epi-v021-ns020-sustained-emergency | 20 | 13 | 0.650 |

- **acc=0 の致命的シナリオ**: ['ns-epi-v021-ns001-boot-sanity', 'ns-epi-v021-ns002-conv-approach', 'ns-epi-v021-ns007-crowd-ambient', 'ns-epi-v021-ns013-scene-degrading']

### 4. 最頻ラベル(定数出力に潰れていないか)

- GT 最頻ラベル: `GOOD`（154 / 210 = 73%）
- supreme 予測最頻ラベル: `DEGRADED`（134 / 210 = 64%）

### 5. 判定(構造ミス A か 未チューニング B か)

**判定: (B) 係数の未チューニング寄り**

根拠:
- GT 語彙の 100% を supreme も出力し、予測も特定クラスへ潰れていない(最頻集中 64%)→ 語彙空間は一致

## 横断的な最重要結論

- **t3_hypothesis**: (A) 語彙/配線の構造ミス寄り
- **scene_regime**: (A) 語彙/配線の構造ミス寄り
- **quality_regime**: (B) 係数の未チューニング寄り

> 判定は観測した語彙集合・混同・集中度のみから導いた(数字の捏造なし)。in-sample のため絶対値は楽観方向に歪み得るが、語彙不一致・定数潰れの有無はin-sample でも構造の問題を示す。

---

_本レポートは supreme.* 公開 API(core)と run_dev_eval の正準化ロジックのみで生成(baseline 非 import・supreme 本体未変更・決定的)。_
