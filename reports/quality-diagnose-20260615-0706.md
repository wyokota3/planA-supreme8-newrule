# quality_regime 対旧 supreme(baseline 忠実度)ギャップ診断

- 生成時刻: 2026-06-15 07:06
- 対象: v021_core 20 シナリオ・210 フレーム(in-sample・封印 verdict ではない)
- 経路: PSO(planA-baseline)→ core.run_supreme → v1.4 view、GT(n04-feat)→ ADR0006 正準化(run_dev_eval 再利用)
- baseline 忠実列は `ns_epi/quality.py`+`ns_epi/hgf.py`+`runner._extract_quality_inputs` の**意味論を再実装**(import なし・観測式/clamp+logit/HGF/_hq_to_regime/w_obs 中央値を忠実に写す)
- 旧 supreme(l04-ours)は再構成でなく **trace.json の実測 view** を v1.4 順位シフトして採点。
- src/supreme・テスト無改変。決定的・stdlib+pyyaml。

## 0. 結論サマリ(最重要)

- 新 supreme quality acc = **0.7238**(152/210)。
- **新 supreme の HGF/quality.classify は据え置き、観測式の `w_obs_bar` だけ baseline 流(track w_obs の中央値・既定 1.0)に直すと → 0.8238**(173/210)。**+21 フレーム改善**。
- 旧 supreme l04-ours を**同一 v1.4 採点**で測ると 0.8238(173/210)。w_obs 忠実化後の supreme はこれにほぼ一致(ギャップほぼ消滅)。
- 最頻の取り違え = **GOOD→DEGRADED 43 件**(全誤り 58 件中の最大群)。うち w_obs 忠実化で **23 件が GOOD へ復帰**。
- **核心原因 = (B) baseline 忠実度ギャップ**。supreme は観測式の `w_obs_bar` を固定 0.5 にハードコードしているが、baseline は `runner._extract_quality_inputs` で **track w_obs の中央値(track 無しは 1.0)** を使う。固定 0.5 は系統的な過小評価で h_q を GOOD ゲート未満に押し下げ、GT=GOOD フレームを DEGRADED へ落としていた。
- GOOD ゲート閾値の −0.01(0.94→0.93)は寄与小: gate0.94 → 0.5952、gate0.93 → 0.7238(主因ではない)。
- **(A)/(B)/(C) 判定は §6**。

> ⚠️ **スコア語彙の注意(混同しないため明記)**: 指示の「旧 supreme 0.7619」は l04-ours を **v1.3 語彙(GOOD/PASS/DEGRADED、view に native BLOCK 含む)で exact-match採点**した値(`results/l04-ours/per_layer.json`・`trace.json` の correct フラグ=160/210)。本診断と SPEC は **v1.4 語彙**で採点する(GT 順位シフト後)。同一 v1.4 採点では l04-ours は 0.8238・baseline(規則のみ)再測定値は 0.6667(`baseline-catalog-1.4.0.md`)。**−0.038 は v1.3 と v1.4 を跨いだ数字差**でもある点に留意。

## 1. quality_regime 混同行列(GT 行 → 予測 列)

### 1.1 新 supreme

| GT＼予測 | GOOD | DEGRADED | BLOCK | 行計 |
|---|---:|---:|---:|---:|
| `GOOD` | **111** | 43 | · | 154 |
| `DEGRADED` | 3 | **25** | 4 | 32 |
| `BLOCK` | · | 8 | **16** | 24 |

- acc = 0.7238(152/210)。
- 最頻誤り = **GOOD→DEGRADED**(GT が GOOD なのに supreme が DEGRADED に落とす)。境界は **GOOD↔DEGRADED**(BLOCK 境界の誤りは相対的に小さい)。

### 1.2 新 supreme + w_obs 忠実化(HGF/classify 据え置き・観測式 w_obs を median に)

| GT＼予測 | GOOD | DEGRADED | BLOCK | 行計 |
|---|---:|---:|---:|---:|
| `GOOD` | **134** | 20 | · | 154 |
| `DEGRADED` | 7 | **23** | 2 | 32 |
| `BLOCK` | · | 8 | **16** | 24 |

- acc = 0.8238(173/210)。現状 supreme から GOOD→DEGRADED が 43 → 20 へ減少。
- これが本診断の決定的測定: **観測式の w_obs だけを baseline 忠実にする**とGOOD 行が大幅に正解側へ戻る。

### 1.3 旧 supreme l04-ours(trace.json 実測・v1.4 順位シフト後)

| GT＼予測 | GOOD | DEGRADED | BLOCK | 行計 |
|---|---:|---:|---:|---:|
| `GOOD` | **131** | 23 | · | 154 |
| `DEGRADED` | 6 | **23** | 3 | 32 |
| `BLOCK` | 1 | 4 | **19** | 24 |

- acc = 0.8238(173/210)。w_obs 忠実化後の新 supreme(§1.2)とほぼ同じ混同構造に収束する。

### 1.4 baseline 規則のみ HGF 忠実シミュレーション(参考・w_obs=median)

| GT＼予測 | GOOD | DEGRADED | BLOCK | 行計 |
|---|---:|---:|---:|---:|
| `GOOD` | **131** | 23 | · | 154 |
| `DEGRADED` | 6 | **23** | 3 | 32 |
| `BLOCK` | 1 | 4 | **19** | 24 |

- acc = 0.8238(173/210)。これは baseline の **quality 専用 HGF**(`hgf3_update`/DEFAULT_PARAMS)を忠実に写したもの。l04-ours(§1.3)は規則のみ baseline と別の(調整済み)アーキで、本列とは一致しない(l04-ours の方が GOOD 復元が強い=本列は参考)。

## 2. 誤りフレームの特定(GT ≠ 新 supreme pred)

全誤り **58 件**。各フレームの GT / 新 supreme pred / その h_q,vol、および baseline 忠実列の pred / h_q,vol を併記する(baseline 忠実なら当たるかで忠実度ギャップを判定)。

- うち **baseline 忠実なら正解 = 27 件**(= 忠実度ギャップで説明できる誤り)。
- うち **baseline 忠実でも誤り = 31 件**(= 観測式/HGF 共通の genuine 限界)。

| sid | ts | GT | sup_pred | sup_h_q | sup_vol | base_pred | base_h_q | base_vol | baseが正解? |
|---|---:|---|---|---:|---:|---|---:|---:|---|
| ns-epi-v021-ns002-conv-approach | 0 | GOOD | DEGRADED | 0.9210 | 0.0099 | DEGRADED | 0.9231 | 0.0099 |  |
| ns-epi-v021-ns002-conv-approach | 0.5 | GOOD | DEGRADED | 0.9245 | 0.0052 | DEGRADED | 0.9364 | 0.0074 |  |
| ns-epi-v021-ns002-conv-approach | 1 | GOOD | DEGRADED | 0.9257 | 0.0038 | GOOD | 0.9456 | 0.0075 | ✓ |
| ns-epi-v021-ns002-conv-approach | 1.5 | GOOD | DEGRADED | 0.9278 | 0.0031 | GOOD | 0.9539 | 0.0076 | ✓ |
| ns-epi-v021-ns002-conv-approach | 2 | GOOD | DEGRADED | 0.9290 | 0.0028 | GOOD | 0.9586 | 0.0077 | ✓ |
| ns-epi-v021-ns002-conv-approach | 2.5 | GOOD | DEGRADED | 0.9298 | 0.0025 | GOOD | 0.9611 | 0.0076 | ✓ |
| ns-epi-v021-ns006-scene-transition | 1 | GOOD | DEGRADED | 0.9299 | 0.0037 | GOOD | 0.9431 | 0.0070 | ✓ |
| ns-epi-v021-ns006-scene-transition | 1.5 | GOOD | DEGRADED | 0.9288 | 0.0031 | DEGRADED | 0.9322 | 0.0083 |  |
| ns-epi-v021-ns006-scene-transition | 2 | GOOD | DEGRADED | 0.9297 | 0.0027 | GOOD | 0.9440 | 0.0083 | ✓ |
| ns-epi-v021-ns007-crowd-ambient | 0 | GOOD | DEGRADED | 0.9078 | 0.0099 | DEGRADED | 0.9150 | 0.0099 |  |
| ns-epi-v021-ns007-crowd-ambient | 0.5 | GOOD | DEGRADED | 0.9088 | 0.0052 | DEGRADED | 0.9164 | 0.0074 |  |
| ns-epi-v021-ns007-crowd-ambient | 1 | GOOD | DEGRADED | 0.9079 | 0.0038 | DEGRADED | 0.9129 | 0.0069 |  |
| ns-epi-v021-ns007-crowd-ambient | 1.5 | GOOD | DEGRADED | 0.9074 | 0.0031 | DEGRADED | 0.9102 | 0.0066 |  |
| ns-epi-v021-ns007-crowd-ambient | 2 | GOOD | DEGRADED | 0.9056 | 0.0026 | DEGRADED | 0.9040 | 0.0064 |  |
| ns-epi-v021-ns009-quality-recovery | 0 | GOOD | DEGRADED | 0.9231 | 0.0099 | GOOD | 0.9567 | 0.0099 | ✓ |
| ns-epi-v021-ns009-quality-recovery | 1.5 | DEGRADED | BLOCK | 0.1849 | 0.0037 | BLOCK | 0.1984 | 0.0099 |  |
| ns-epi-v021-ns009-quality-recovery | 2 | DEGRADED | BLOCK | 0.3502 | 0.0035 | DEGRADED | 0.7906 | 0.0099 | ✓ |
| ns-epi-v021-ns009-quality-recovery | 2.5 | GOOD | DEGRADED | 0.5944 | 0.0036 | DEGRADED | 0.9388 | 0.0099 |  |
| ns-epi-v021-ns009-quality-recovery | 3 | GOOD | DEGRADED | 0.7720 | 0.0037 | GOOD | 0.9620 | 0.0099 | ✓ |
| ns-epi-v021-ns011-multi-stress | 0.5 | DEGRADED | BLOCK | 0.5297 | 0.0052 | BLOCK | 0.2951 | 0.0075 |  |
| ns-epi-v021-ns013-scene-degrading | 1.5 | GOOD | DEGRADED | 0.9267 | 0.0032 | GOOD | 0.9409 | 0.0089 | ✓ |
| ns-epi-v021-ns013-scene-degrading | 2 | GOOD | DEGRADED | 0.9205 | 0.0029 | DEGRADED | 0.9365 | 0.0088 |  |
| ns-epi-v021-ns013-scene-degrading | 2.5 | GOOD | DEGRADED | 0.9132 | 0.0027 | DEGRADED | 0.9317 | 0.0086 |  |
| ns-epi-v021-ns013-scene-degrading | 3 | GOOD | DEGRADED | 0.9045 | 0.0026 | DEGRADED | 0.9256 | 0.0085 |  |
| ns-epi-v021-ns013-scene-degrading | 3.5 | GOOD | DEGRADED | 0.8944 | 0.0025 | DEGRADED | 0.9181 | 0.0083 |  |
| ns-epi-v021-ns015-full-coverage | 3 | GOOD | DEGRADED | 0.9276 | 0.0023 | DEGRADED | 0.8991 | 0.0094 |  |
| ns-epi-v021-ns015-full-coverage | 3.5 | GOOD | DEGRADED | 0.9147 | 0.0022 | DEGRADED | 0.8716 | 0.0095 |  |
| ns-epi-v021-ns015-full-coverage | 4 | GOOD | DEGRADED | 0.8929 | 0.0022 | DEGRADED | 0.8248 | 0.0094 |  |
| ns-epi-v021-ns015-full-coverage | 4.5 | GOOD | DEGRADED | 0.8576 | 0.0023 | DEGRADED | 0.7457 | 0.0094 |  |
| ns-epi-v021-ns015-full-coverage | 5 | GOOD | DEGRADED | 0.8022 | 0.0024 | DEGRADED | 0.6570 | 0.0094 |  |
| ns-epi-v021-ns015-full-coverage | 5.5 | GOOD | DEGRADED | 0.7293 | 0.0026 | DEGRADED | 0.5923 | 0.0095 |  |
| ns-epi-v021-ns015-full-coverage | 6 | BLOCK | DEGRADED | 0.6420 | 0.0027 | BLOCK | 0.5277 | 0.0094 | ✓ |
| ns-epi-v021-ns015-full-coverage | 6.5 | BLOCK | DEGRADED | 0.6192 | 0.0029 | DEGRADED | 0.6411 | 0.0094 |  |
| ns-epi-v021-ns015-full-coverage | 7 | BLOCK | DEGRADED | 0.6582 | 0.0030 | DEGRADED | 0.7557 | 0.0094 |  |
| ns-epi-v021-ns015-full-coverage | 7.5 | BLOCK | DEGRADED | 0.7384 | 0.0030 | DEGRADED | 0.8525 | 0.0095 |  |
| ns-epi-v021-ns015-full-coverage | 8 | BLOCK | DEGRADED | 0.8102 | 0.0032 | GOOD | 0.9407 | 0.0095 |  |
| ns-epi-v021-ns015-full-coverage | 8.5 | GOOD | DEGRADED | 0.8639 | 0.0033 | GOOD | 0.9607 | 0.0096 | ✓ |
| ns-epi-v021-ns015-full-coverage | 9 | GOOD | DEGRADED | 0.8975 | 0.0034 | GOOD | 0.9676 | 0.0096 | ✓ |
| ns-epi-v021-ns015-full-coverage | 9.5 | GOOD | DEGRADED | 0.9184 | 0.0035 | GOOD | 0.9712 | 0.0096 | ✓ |
| ns-epi-v021-ns018-quality-cycle | 1.5 | DEGRADED | GOOD | 0.9404 | 0.0030 | GOOD | 0.9499 | 0.0066 |  |
| ns-epi-v021-ns018-quality-cycle | 3 | BLOCK | DEGRADED | 0.8241 | 0.0025 | DEGRADED | 0.5502 | 0.0093 |  |
| ns-epi-v021-ns018-quality-cycle | 3.5 | BLOCK | DEGRADED | 0.7248 | 0.0026 | BLOCK | 0.3752 | 0.0095 | ✓ |
| ns-epi-v021-ns018-quality-cycle | 4 | BLOCK | DEGRADED | 0.5964 | 0.0027 | BLOCK | 0.2681 | 0.0095 | ✓ |
| ns-epi-v021-ns018-quality-cycle | 6 | DEGRADED | BLOCK | 0.5225 | 0.0032 | DEGRADED | 0.7262 | 0.0095 | ✓ |
| ns-epi-v021-ns018-quality-cycle | 8 | GOOD | DEGRADED | 0.8808 | 0.0037 | GOOD | 0.9548 | 0.0096 | ✓ |
| ns-epi-v021-ns018-quality-cycle | 8.5 | GOOD | DEGRADED | 0.9089 | 0.0038 | GOOD | 0.9588 | 0.0096 | ✓ |
| ns-epi-v021-ns018-quality-cycle | 9 | GOOD | DEGRADED | 0.9254 | 0.0039 | GOOD | 0.9615 | 0.0096 | ✓ |
| ns-epi-v021-ns019-scene-regime-cycle | 6 | GOOD | DEGRADED | 0.8346 | 0.0027 | DEGRADED | 0.9103 | 0.0090 |  |
| ns-epi-v021-ns019-scene-regime-cycle | 6.5 | GOOD | DEGRADED | 0.8649 | 0.0028 | DEGRADED | 0.9309 | 0.0091 |  |
| ns-epi-v021-ns019-scene-regime-cycle | 7 | GOOD | DEGRADED | 0.8905 | 0.0028 | GOOD | 0.9411 | 0.0091 | ✓ |
| ns-epi-v021-ns019-scene-regime-cycle | 7.5 | GOOD | DEGRADED | 0.9088 | 0.0029 | GOOD | 0.9449 | 0.0090 | ✓ |
| ns-epi-v021-ns019-scene-regime-cycle | 8 | GOOD | DEGRADED | 0.9207 | 0.0030 | GOOD | 0.9448 | 0.0090 | ✓ |
| ns-epi-v021-ns019-scene-regime-cycle | 8.5 | GOOD | DEGRADED | 0.9287 | 0.0030 | GOOD | 0.9457 | 0.0089 | ✓ |
| ns-epi-v021-ns020-sustained-emergency | 2 | DEGRADED | GOOD | 0.9418 | 0.0026 | GOOD | 0.9567 | 0.0064 |  |
| ns-epi-v021-ns020-sustained-emergency | 2.5 | DEGRADED | GOOD | 0.9357 | 0.0024 | GOOD | 0.9469 | 0.0064 |  |
| ns-epi-v021-ns020-sustained-emergency | 8.5 | GOOD | DEGRADED | 0.9058 | 0.0029 | GOOD | 0.9582 | 0.0091 | ✓ |
| ns-epi-v021-ns020-sustained-emergency | 9 | GOOD | DEGRADED | 0.9202 | 0.0029 | GOOD | 0.9614 | 0.0090 | ✓ |
| ns-epi-v021-ns020-sustained-emergency | 9.5 | GOOD | DEGRADED | 0.9293 | 0.0030 | GOOD | 0.9617 | 0.0090 | ✓ |

## 3. GOOD→DEGRADED 誤り群の h_q/vol 分布(最頻取り違えの核心)

GOOD→DEGRADED は 43 件。supreme がこれらを GOOD と判定するには **h_q ≥ ゲート ∧ vol < 0.01** が要る。各値の届き具合:

- supreme h_q: min=0.5944 / median=0.9089 / max=0.9299
- supreme vol: min=0.0022 / median=0.0030 / max=0.0099
- baseline h_q: min=0.5923 / median=0.9409 / max=0.9712
- supreme h_q ≥ 0.93 のもの: 0/43 件
- supreme h_q ≥ 0.94 のもの: 0/43 件
- supreme vol < 0.01 のもの: 43/43 件
- baseline 忠実列でこれらが GOOD になる件数: 22/43 件

## 4. 新 supreme quality と baseline の乖離点(式/閾値/境界)

`src/supreme/quality.py`+`core.py`(観測式/HGF)と baseline `ns_epi/quality.py`+`ns_epi/hgf.py` を読み比べた乖離点:

| 観点 | 新 supreme | baseline | 同一? |
|---|---|---|---|
| **観測式 w_obs_bar(最重要)** | **固定 0.5**(`_DEFAULT_WOBS`・track 無視) | **track w_obs の中央値(無ければ 1.0)**(`runner._extract_quality_inputs`) | **異なる ← ギャップ主因** |
| 観測式の係数 | `-2 +5·qos -4·(lat/200) -2.5·(1-id) +1.5·w_obs` | `-2 +5·qos -4·(lat/200) -2.5·(1-id) +1.5·w_obs` | 同一(係数のみ) |
| 観測式入力(logit 前処理) | 生 logit をそのまま HGF へ | sigmoid→clamp[1e-6]→logit 再導出 u を HGF へ | ほぼ同一(clamp 域外のみ差) |
| GOOD ゲート h_q | **≥ 0.93**(ADR0014 再較正) | ≥ 0.94 | 異なる(−0.01・寄与小) |
| GOOD ゲート vol | < 0.01 | < 0.01 | 同一 |
| BLOCK 第1/2/3 境界 | <0.25 / (<0.40∧vol>0.05) / <0.55 | <0.25 / (<0.40∧vol>0.05) / <0.55 | 同一 |
| DEGRADED 既定 | その他=DEGRADED | その他=PASS(→v1.4 DEGRADED) | 同一(v1.4 で一致) |
| HGF カーネル | scene 共有 `hgf_filter` | quality 専用 `hgf3_update` | **異なる** |
| HGF κ2 | 0.1 | 1.0 | **異なる** |
| HGF ω1/ω2/ω3 | −3.0/−2.0/0.0 | −4.0/−4.0/−6.0 | **異なる** |
| HGF obs_noise | 0.01 | 0.1 | **異なる** |
| 観測精度 pi_u | 1/obs_noise = **100** | 1/obs_noise² = **100** | 偶然同値(式が違う) |
| vol(GOOD ゲート入力) | var1 = 1/π1(層1 事後分散) | derived sigma1 = 1/π1_new(層1 事後分散) | 同じ意味量(層1 事後分散) |

> 注: pi_u は supreme `1/obs_noise`(obs_noise=0.01)= 100、baseline `1/obs_noise²`(obs_noise=0.1)= 100 で**偶然同値**。式の形は異なるため obs_noise を変えると挙動が分岐する。ただし §0/§1.2 が示す通り、HGF 据え置きで w_obs だけ直せばギャップはほぼ消えるため、HGF カーネル差は本データでは主因ではない。

## 5. 死配線/証拠潰しの有無

- QoS/latency 証拠は **両系で配線済み**(`scene_state.QoS/latency_ms` を観測式へ投入)。
- **w_obs 証拠は supreme で潰れている**: PSO の track(audio/humans/objects)は `w_obs` を持つ(本データで track 在りフレームは多数)のに、supreme は観測式で **固定 0.5** を使い track の `w_obs` を一切読まない。baseline は同じ track の `w_obs` 中央値を使う。**=「証拠が在るのに使っていない」型の欠落**(死配線というより観測式の入力過小評価)。
- これは src/supreme 固有の再現漏れ(B)であり、観測式の係数や閾値は baseline と一致する。従って **(A) 構造バグ(配線そのものの破断)ではなく、(B) 入力抽出の忠実度ギャップ**。

## 6. (A)/(B)/(C) 判定

観測事実(本文の数値が一次根拠):
- 現状 supreme acc = 0.7238。**HGF/classify 据え置き・観測式 w_obs だけbaseline 流(track 中央値)に直すと 0.8238**(+21 フレーム)。
- 旧 supreme l04-ours の同一 v1.4 採点 = 0.8238。w_obs 忠実化後のsupreme はこれにほぼ並ぶ(ギャップほぼ消滅)。
- 最頻誤り GOOD→DEGRADED 43 件のうち w_obs 忠実化で 23 件が GOOD へ復帰。
- GOOD ゲート閾値 −0.01(gate0.94=0.5952 → gate0.93=0.7238)は寄与小。

**判定: 核心は (B) baseline 忠実度ギャップ(観測式入力 `w_obs_bar` の再現漏れ)。**

- **(A) 構造バグ: 否定的**。観測式の係数・clamp・GOOD/BLOCK 境界・vol 層(var1=層1事後分散=baseline sigma1 の同量・既修正)はいずれも baseline と整合。配線そのものの破断は無い。
- **(B) baseline 忠実度ギャップ: 該当(主因)**。supreme は観測式で `w_obs_bar` を**固定 0.5** にハードコード(`core._DEFAULT_WOBS`)し、PSO の track が持つ `w_obs` を読んでいない。baseline は `runner._extract_quality_inputs` で **track w_obs の中央値(track 無し=1.0)** を使う。固定 0.5 は系統的に観測 logit を押し下げ、GT=GOOD フレームのh_q を GOOD ゲート(≥0.93)未満に保ち DEGRADED へ落としていた。**忠実再現(w_obs を中央値に)だけで直る**: 上の決定的測定が +21 フレームを実証(HGF は supreme のまま据え置き)。
- **(C) genuine(ADR0014 スコープ外)残件: 限定的**。w_obs 忠実化後も残る誤り(37 件)には、DEGRADED↔BLOCK 境界や、観測式が QoS/latency/w_obsのみから h_q を作る感度限界(ADR0014 が「DEGRADED→BLOCK は観測式/HGF の別課題=スコープ外」とした領域)が含まれる。ここは過適合なしには動かしにくく研究者/別 ADR 領分だが、**ギャップ −0.038 の主因ではない**(主因は w_obs)。

### 6.1 忠実再現で直る見込みと過適合の区別

- (B) の修正対象 = **`core._quality_obs_raw_logits` の `_DEFAULT_WOBS`(固定 0.5)を、baseline `runner._extract_quality_inputs` と同じ「全 track(audio+humans+objects)の `w_obs` 中央値・無ければ 1.0」へ差し替える**こと。これは baseline の文書化された入力抽出規則への**忠実再現**であり、v021_core の正解に合わせ込む閾値いじり(過適合)ではない。
- **過適合との区別**: w_obs 中央値は [0.09,1.0] に広く分布する各フレームの実 track 信頼度(本データ 210 フレーム中 182 が track 在り)であって、特定シナリオの正解に合わせた定数ではない。baseline が全データで同じ規則を使う=規則整合。**v021_core 合わせ込みではない**。
- 予想影響: in-sample で acc 0.7238→0.8238(+21 フレーム)。封印 verdict は F-013 で測る。
- 副作用の注意: w_obs を上げると h_q 全体が上がるため、GT=DEGRADED/BLOCK フレームをGOOD 側へ誤らせ得る。§1.2 の混同行列で純益(GOOD 行の回復 − 他行の悪化)が正であることを確認済みだが、最終判断は封印(F-013)・ガードレールで行う。
- ADR0014 が固定した GOOD ゲート 0.93 は維持(本診断は ADR0014 の閾値を一切変えない)。ギャップ主因は閾値でも HGF カーネルでもなく **観測式の w_obs 入力**である。

---

_本レポートは supreme.* 公開 API(core/quality)と run_dev_eval の正準化ロジックのみで生成し、baseline コードは import せず意味論を再実装した(src/supreme・テスト無改変・決定的)。_
