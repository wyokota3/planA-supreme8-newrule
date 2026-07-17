# 差分監査レポート: quality w_obs 忠実再現修正(診断 B)

日時: 2026-06-15 07:15
対象: `src/supreme/core.py` の `_w_obs_bar(snap)` 追加 + `_quality_obs_raw_logits` の w_obs 入力是正(固定 0.5 → track w_obs 中央値)
種別: 差分監査(read-only・引用付き)・WORKFLOW ステップ7
ノード: F-基盤-001(core / epiin)— quality/scene/t3 の上流

---

## サマリ

- **忠実再現か過適合か**: **忠実再現**(過適合ではない)。判定根拠は §1。
- 検証4点: 1=pass / 2=pass(条件付き注記あり) / 3=pass / 4=pass
- 後方互換: 保持(テスト fixtures は w_obs を持たず新既定 1.0 で動く・旧 0.5 を pin するテストは存在しない)
- スコープ: w_obs 1点のみ(係数/境界/vol/HGF/quality.classify 無改変を引用確認)
- オーバー実装: なし
- リスク: **中**(コード論理は健全。リスクは「テスト緑で出ない穴」= w_obs 経路の回帰テストが皆無・偽陽性が封印 held-out で効く可能性。§穴 参照)
- done 可否: **done 可**(条件 = 偽陽性の最終判定を F-013 封印で行う旨を申し送り + 軽微な腐れコメント是正の申し送り)

---

## 検証1(★最重要★): 忠実再現か過適合か

### 実装の引用

`src/supreme/core.py:211-236`(`_w_obs_bar`):
```python
def _w_obs_bar(snap):
    ...
    w_obs_values = []
    for t in _audio_tracks(snap) + _human_tracks(snap) + _object_tracks(snap):
        if "w_obs" in t:
            w_obs_values.append(float(t["w_obs"]))
    if w_obs_values:
        return statistics.median(w_obs_values)
    return _DEFAULT_WOBS
```
`_DEFAULT_WOBS = 1.0`(`src/supreme/core.py:94`)。

### 構造判定のみであることの引用確認

- 対象 track = `_audio_tracks(snap) + _human_tracks(snap) + _object_tracks(snap)`(全 track 連結)。`_audio_tracks` 等は `snap.get("tracks", {}).get("audio", [])`(`core.py:163-173`)で、**track の構造(group キー)のみ**を見る。
- 母集団判定は `if "w_obs" in t`(`core.py:233`)= **フィールドの存在のみ**で母集団を決める。`w_obs` を持たない track は母集団に**含めない**(既定補完しない)。
- 集計は `statistics.median(...)`(`core.py:235`)= 値そのものの中央値。
- 空母集団 → `_DEFAULT_WOBS = 1.0`(`core.py:236`)。

→ **特定 ts / 特定シナリオ ID / 特定フレーム番号への依存は一切無い**。コード中に `sid`・`ts`・シナリオ名・マジックなフレーム index は出現しない(`type`/track 構造の判定のみ)。

### baseline 規則との一致(再実装意味論の突合)

baseline `runner._extract_quality_inputs` 本体は本リポジトリに vendored されていない(`external-data/planA-baseline/src/ns_epi/runner.py` は存在せず・後述の制約)。そのため baseline コードの行番号引用は不可。代わりに、診断スクリプトが「import せず意味論を再実装」した baseline 写し `scripts/run_quality_diagnose.py:182-194`(`_baseline_w_obs_bar`)と新 `core._w_obs_bar` を突合する:

```python
# scripts/run_quality_diagnose.py:182-194
def _baseline_w_obs_bar(snap):
    """baseline runner._extract_quality_inputs と同一: 全 track の w_obs 中央値・無ければ 1.0。"""
    tracks = snap.get("tracks", {}) or {}
    vals = []
    for grp in ("audio", "humans", "objects"):
        for t in (tracks.get(grp, []) or []):
            if "w_obs" in t:
                vals.append(float(t["w_obs"]))
    return statistics.median(vals) if vals else 1.0
```

両者は**意味論完全一致**: (a) 対象 = audio+humans+objects 全 track、(b) `"w_obs" in t` を持つもののみ母集団、(c) median、(d) 空なら 1.0。

ADR の文書化された規則とも一致する:
- `decisions/0022-fbase001-supreme-runner.md:32`(決定3)が観測式を `logit = -2 + 5·qos - 4·(latency/200) - 2.5·(1-id_const) + 1.5·w_obs_bar` と明記し、`w_obs_bar` を**定義済み入力**として記述。
- `decisions/0022...:6` が source of truth を baseline `external-data/planA-baseline/src/ns_epi/{runner,...}.py` と明示。

旧実装は ADR 0022 の観測式で `w_obs_bar` を要求しながら、`core.py` で固定 0.5 にハードコードしていた(=ADR が定義した入力契約の再現漏れ)。本修正はその穴を埋める。

### 過適合でないことの引用確認

- 中央値は各フレームの実 track 信頼度であり、特定シナリオの正解に合わせた定数ではない(診断 `reports/quality-diagnose-20260615-0706.md:191`: w_obs 中央値は [0.09,1.0] に広く分布・210 フレーム中 182 が track 在り)。
- 閾値(GOOD ゲート 0.93/vol 0.01)・観測式係数は**一切変えていない**(検証4で引用)。すなわち「v021_core の正解に合わせ込む閾値いじり」ではない。

### 判定(検証1)

**忠実再現である。v021_core 合わせ込み(過適合)ではない。** `type`/track 構造とフィールド存在のみで母集団を決め、特定 ts/シナリオ依存が無い。baseline 再実装写し(diagnose 1882-194)・ADR 0022 決定3 の観測式定義と意味論一致。**判定: pass**。

> 制約(誠実性のため明記): baseline `ns_epi/runner.py` 実体が本リポジトリに無いため、baseline の **一次ソース行番号**は引用できなかった。突合は (a) ADR 0022 決定3 の観測式文書、(b) 診断スクリプトの「import せず再実装した baseline 写し」の2つに対して行った。両者は一致するが、baseline 一次ソースとの最終突合は別環境(planA-baseline チェックアウト)でのみ可能。これは本修正の瑕疵ではなくリポジトリ構成上の制約。

---

## 検証2: 波及の純影響(h_q → quality/scene/t3/mode)

### dev-eval 全8層 before→after(in-sample・楽観値)

`reports/dev-eval-BEFORE-wobs.md:31-38` と `reports/dev-eval-AFTER-wobs.md:31-38` の既定列を対照:

| 層 | BEFORE 既定 | AFTER 既定 | Δ | 悪化か |
|---|---:|---:|---:|---|
| risk_tier | 0.9333 | 0.9333 | +0.0000 | 不変 |
| t1_state | 0.9095 | 0.9095 | +0.0000 | 不変 |
| t2_role | 0.9571 | 0.9571 | +0.0000 | 不変 |
| t2_mode | 0.6238 | 0.6286 | **+0.0048** | 微増 |
| t2_relation | 0.8381 | 0.8381 | +0.0000 | 不変 |
| t3_hypothesis | 0.3905 | 0.3952 | **+0.0047** | 微増 |
| scene_regime | 0.4524 | 0.4524 | +0.0000 | 不変 |
| quality_regime | 0.7238 | 0.8238 | **+0.1000** | 主目的 |

- **quality +0.10**(0.7238→0.8238)= 指示の期待値に一致。
- 他層は **微増(t2_mode +0.0048・t3 +0.0047)or 不変**。**悪化層ゼロ**。
- 波及経路は妥当: w_obs↑→ h_q↑。h_q は t2_mode(`core.py:391` の `if h_q < 0.5: env_change`)と t3(`core.py:633` の `posterior=h_q`)に流れる。h_q が上がると低品質フレームの env_change 発火が減り(t2_mode 微増)、t3 の posterior ゲート(ADR0026・`< 0.40` で uncertain 是正)挙動が変わる(t3 微増)。scene は `_scene_health_signal`(sigmoid 済み health)経由で h_q 上昇の影響を受けうるが、既定列は **0.4524 不変**(scene の nominal=信号中央値結線が水準シフトを吸収するため・`core.py:509-522`)。

→ **quality +0.10・他層は微増 or 不変・悪化層ゼロ。判定: pass**。

### 学習層 scene/t3 の CV held-out(正準・非悪化)

`reports/cv-train-BEFORE-wobs.md` vs `cv-train-AFTER-wobs.md` の held-out 全体:

| 層 | BEFORE held-out 既定→学習 | AFTER held-out 既定→学習 |
|---|---|---|
| t3_hypothesis | 0.3905 → 0.5333 | 0.3952 → **0.5381** |
| scene_regime | 0.3238 → 0.5571 | 0.3238 → **0.5571** |

- **t3 held-out 学習 0.5333 → 0.5381(+0.0048・非悪化)**(`cv-train-AFTER-wobs.md:32`)。fold 別でも全 fold 非悪化(fold4 が 0.5952→0.6071 と改善・他 fold は同値: BEFORE `:27-31` vs AFTER `:27-31`)。
- **scene held-out 完全不変**(既定 0.3238・学習 0.5571 ともに前後一致・`cv-train-AFTER-wobs.md:43`)。全 fold 値も一致。
- in-sample 楽観(dev-eval 学習列 t3 0.5333→0.5381)と held-out 正準を**区別**して確認した。held-out が汎化の正直な推定であり、ここで非悪化が取れている。

→ **学習層 scene/t3 の CV held-out が非悪化(t3 微増・scene 不変・全 fold 非悪化)。判定: pass**。

---

## 検証3: quality 偽陽性の純益

`reports/quality-diagnose-20260615-0706.md:26-44` の混同行列(GT 行 → 予測 列)を before/after で対照:

**BEFORE(§1.1)**:
| GT＼予測 | GOOD | DEGRADED | BLOCK |
|---|---:|---:|---:|
| GOOD | 111 | 43 | · |
| DEGRADED | 3 | 25 | 4 |
| BLOCK | · | 8 | 16 |

**AFTER / w_obs 忠実化(§1.2)**:
| GT＼予測 | GOOD | DEGRADED | BLOCK |
|---|---:|---:|---:|
| GOOD | 134 | 20 | · |
| DEGRADED | 7 | 23 | 2 |
| BLOCK | · | 8 | 16 |

純益の内訳:
- **GOOD 回復**: GOOD→GOOD が 111→134 = **+23**(GOOD→DEGRADED は 43→20 = −23 と整合)。
- **偽陽性(GT≠GOOD なのに GOOD 予測)**: DEGRADED→GOOD が 3→7 = **+4**。BLOCK→GOOD は 0→0(**BLOCK 漏れ 0**・安全側が崩れていない)。
- **BLOCK 行**: 完全不変(16/8/·)。w_obs 引き上げが最重度クラスを侵食していない。
- **DEGRADED→BLOCK**(より安全側へ): 4→2(2件改善)。

純益 = +23(GOOD 回復) − 4(偽陽性) = **+19 純正**。指示の「GOOD回復+23 vs 偽陽性+4・BLOCK漏れ0」と一致。最も安全上重要な BLOCK の取りこぼし(BLOCK→GOOD)が **0** であることが特に重要。

→ **純益が正(+23 vs +4・BLOCK 漏れ 0)。判定: pass**。

> 注意(検証3の穴): この混同行列は **in-sample(v021_core 210 フレーム)**。偽陽性 +4 は DEGRADED→GOOD であり、安全マージン上は BLOCK 漏れより軽微だが、封印 held-out では in-sample より偽陽性比率が上振れし得る(w_obs↑は h_q を一律押し上げるため、GT=DEGRADED 境界フレームを GOOD へ倒すリスクが構造的に残る)。§穴 R2 参照。

---

## 検証4: 後方互換・スコープ・テスト

### スコープ = w_obs 1点のみ(無改変の引用)

- **観測式係数 無改変**: `_OBS_BIAS=-2.0`/`_OBS_QOS=5.0`/`_OBS_LATENCY=-4.0`/`_OBS_ID=-2.5`/`_OBS_WOBS=1.5`(`core.py:84-88`)。`_quality_obs_raw_logits`(`core.py:424-430`)は係数構造を保ち、`w_obs_bar` の供給源だけ `_w_obs_bar(snap)`(`core.py:423`)に変えた。
- **quality 境界 無改変**: `src/supreme/quality.py:50-58`(`classify`)の優先順位チェーン(<0.25/<0.40∧vol>0.05/<0.55/≥0.93∧vol<0.01)は変更なし。
- **vol 無改変**: `_hq_vol_sequences`(`core.py:449-469`)は `vol = list(htraj.var1)`(層1 事後分散)を据え置き。
- **HGF 無改変**: `scene_mod.hgf_filter(quality_logits, scene_mod.default_hgf_params())`(`core.py:466`)= 共有カーネル・既定 param そのまま。
- `_DEFAULT_WOBS` の参照箇所は `_w_obs_bar` のみ(`core.py:236` + docstring)。他の `0.5`(`core.py:391` env_change の `h_q<0.5`・`core.py:92` `_DEFAULT_QOS`・`core.py:512` scene nominal)は**別物で無改変**(`Grep _DEFAULT_WOBS|0\.5` で確認)。

→ **変更は w_obs 1点のみ。係数/境界/vol/HGF 無改変。判定: pass**。

### 旧 w_obs=0.5 を pin するテストが無い(落ちていない)ことの確認

- `tests/` 全体で `w_obs` / `_w_obs_bar` / `_DEFAULT_WOBS` への参照は **0 件**(`Grep` 結果: No matches)。旧 0.5 を pin するテストも、新 1.0/median を pin するテストも**存在しない**。よって本修正でテストが落ちる経路は構造的に無い。
- quality を直接突くテスト `tests/test_F011_classify_rule.py` は `quality.classify(h_q, vol)` を**直接**呼ぶ(例 `:40` `classify(0.93, 0.009)`)。`_w_obs_bar` を一切経由しないため**完全に絶縁**。

### fixtures が w_obs 無し → 1.0 default の整合

- `tests/fixtures_pso.py` の `audio_track`(`:71-74`)/`human_track`(`:77-84`)/`object_track`(`:87-90`)は `w_obs` を設定しない(`**extra` 経由で渡されない限り付かない)。各 `frame_*` ビルダ(`:112-176`)も `w_obs` を渡さない。
- → テスト fixtures の全 track は `w_obs` を持たず、`_w_obs_bar` は全フレームで `_DEFAULT_WOBS = 1.0` を返す。fixtures と新 default が整合する。

### 結線テスト(quality 感度経路)が新 default で緑のままか — 数値検証

`tests/test_Fbase001_wiring.py` の2つの方向性アサーションを新 w_obs=1.0 で確認:

- **low_qos → DEGRADED/BLOCK が現れる**(`:215-229`): `frame_low_qos(qos=0.05, latency_ms=190.0)`。logit = -2 + 5·0.05 - 4·(190/200) + 1.5·1.0 = -2 + 0.25 - 3.8 + 1.5 = **-4.05**。h_q=sigmoid(μ1) は強い負 logit に追従し ≪0.55 → BLOCK 側。w_obs を 0.5→1.0 にしても +0.75 しか上がらず(logit -4.8→-4.05)依然 GOOD ゲート遠方。**`any(r in DEGRADED_BLOCK)` は満たされる**(緑のまま)。
- **benign → GOOD が現れる**(`:232-246`): `frame_benign(qos=0.95, latency_ms=20.0)`。logit = -2 + 5·0.95 - 4·(20/200) + 1.5·1.0 = -2 + 4.75 - 0.4 + 1.5 = **+3.85**。w_obs 1.0 は旧 0.5 より +0.75 高く、h_q を GOOD ゲート(≥0.93)に**より確実に**届かせる。**`any(r == "GOOD")` は満たされる**(緑のまま・むしろ余裕増)。

→ 方向性アサーションは新 default で両方緑。**795 テスト全緑の主張は、quality 感度経路に関して整合**(全 795 実走は本監査の read-only スコープ外だが、落ちる経路が無いことを引用と数値で確認した)。**判定: pass**。

---

## アーキテクチャ上の位置づけ

- 実現ノード: `core` / `epiin`(F-基盤-001)。本修正は core の観測式入力抽出の是正。
- 充足度: ADR 0022 決定3 が定義した観測式 `... + 1.5·w_obs_bar` の **w_obs_bar 入力をようやく契約どおり供給**(従来は固定 0.5 で契約未充足だった)→ 充足度が**部分→完全**へ近づく。
- 上流(入力元)の未実装: なし。PSO track の `w_obs` は既に入力に在り(`_w_obs_bar` が読む)。
- 下流(出力先)への波及: `quality`(直接)/`scene`/`t3`/`t2_mode`(h_q 経由)。検証2で全層非悪化を確認済み。
- **図とコードのズレ**: `specs/status.json` の edges(epiin→quality 等)とコードの結線は整合。ただし **コメントの腐れを1件検出**(下記オーバー実装/腐れ §)。

---

## オーバー実装の検出

仕様にない実装の追加: **なし**。`_w_obs_bar` は ADR 0022 決定3 の観測式が要求する入力の抽出であり、新規機能の追加ではない。

### 図・コメントとコードのズレ(腐れ)1件

`src/supreme/core.py:81`(モジュール冒頭の観測式コメント):
```python
# id_const は 1.0 固定(=寄与項 0)。w_obs_bar は観測重みの平均(縮退既定 0.5)。
```
このコメントは**未更新**で、(a)「平均」→実際は中央値(median)、(b)「縮退既定 0.5」→実際は 1.0(`_DEFAULT_WOBS=1.0`)と**二重に現状コードと矛盾**する。論理には影響しないが、図(コメント)が腐っている。実装本体の docstring(`core.py:211-228`・`409-418`)は正しく中央値/1.0 を記述しているため、矛盾は冒頭コメント1行に局所化されている。

→ **是正推奨(低優先・ドキュメント整合)**: `core.py:81` を「w_obs_bar は全 track の w_obs 中央値(track 無しは 1.0)」へ更新。

---

## テスト緑では出ない穴(必須記録)

- **R1(高): w_obs 経路の回帰テストが皆無**。`tests/` 全体で `w_obs`/`_w_obs_bar` を突くテストが 0 件。本修正の核心挙動((a)全 track 連結の中央値、(b)`w_obs` 無し track は母集団外、(c)空母集団→1.0、(d)audio/humans/objects 混在の中央値)は**どのテストにも pin されていない**。誰かが将来 `_w_obs_bar` を「平均」や「全 track 既定 0.5 補完」に書き換えても**全テスト緑のまま通る**(fixtures が w_obs を持たないため検出不能)。→ `w_obs` を持つ合成 track を含む fixture を追加し、(a)〜(d)を pin する回帰テストを追加すべき(WORKFLOW ステップ2 相当の追補)。
- **R2(中): 偽陽性が封印 held-out で効く可能性**。検証3の偽陽性 +4(DEGRADED→GOOD)は in-sample 値。w_obs↑は h_q を構造的に一律押し上げるため、封印セットで GT=DEGRADED の境界フレーム比率が高い場合、GOOD 偽陽性が in-sample より増え得る。BLOCK→GOOD は in-sample 0 だが封印で 0 が保証されているわけではない。→ 最終判定は **F-013 封印**で行う旨を done 条件に明記(診断 `:193` も同旨)。
- **R3(低): scene/t3 への隠れ波及**。scene 既定は in-sample/held-out とも不変だが、これは `_scene_health_signal`(sigmoid 済み)+ nominal=信号中央値結線(`core.py:509-522`)が水準シフトを吸収する設計に依存する。w_obs 分布が封印セットで大きく異なれば nominal 推定がずれ、scene_regime が動く理論的余地が残る(in-sample では検出されていない)。t3 は posterior=h_q ゲート(ADR0026 `<0.40`)経由で h_q 上昇が uncertain 是正の発火頻度を下げる方向に効く。held-out 非悪化は確認済みだが、封印での再確認が望ましい。

---

## 推奨アクション

1. **(申し送り・done をブロックしない)** R1: `_w_obs_bar` の (a)全 track 中央値 / (b)w_obs 無し→母集団外 / (c)空→1.0 / (d)混在中央値 を pin する回帰テストを追加(次の小機能として）。
2. **(申し送り・done をブロックしない)** R2/R3: 偽陽性・scene/t3 波及の最終判定を F-013 封印で行う(in-sample/CV held-out では純益正・非悪化を確認済み)。
3. **(低優先・任意)** 腐れコメント `src/supreme/core.py:81` を中央値/既定1.0 へ更新(図とコードの整合)。

---

AUDIT_VERDICT: pass
