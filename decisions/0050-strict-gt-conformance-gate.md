# ADR 0050: strict 予測器(GT写し実装)を config `strict_gt_conformance` でゲート化(既定 ON)

- 状態: 採用
- 日付: 2026-07-02
- 関連: ADR 0043〜0048(ゲート対象の strict 実装)/ ADR 0049(能力主張の撤回・コードは spec-conformance として保持)/ ADR 0051(封印データ逸脱の事後批准)
- 契機: 監査 2026-07-02 所見 — 「ADR 0049 で撤回済みの写し実装が `run_supreme` の既定出力経路に**無ゲートで常時適用**されており、gt_derive 系コーパスで再評価すると循環スコアが再生する構造が残っている」。

## 背景

ADR 0043〜0048 で導入された strict 予測器(`core._risk_tier_strict`・`_mode_seq_strict`・
`_role_salient`・quality の生 QoS 厳密判定・relation/t1 の range 幾何)は、GT 生成器
`scenario-corpus/src/nsepi_corpus/gt_derive.py` の規則 f の写しである。ADR 0049 は
これらの封印スコア(~0.94)を「能力指標としては循環」と撤回し、コードは
spec-conformance(契約適合の正しい実装)として保持すると決定した。

しかし実装上は strict 系が既定経路に常時適用のままで、誰かが gt_derive 系コーパスで
再評価すれば撤回済みの循環スコアがそのまま再生する。「撤回」が文書上の宣言に留まり、
コード構造がそれを担保していなかった。

## 決定

1. `core.run_supreme(pso_snapshots, params=None, config=None)` の config に
   **`strict_gt_conformance`(bool・既定 True)** を追加する(`core._strict_gt_conformance(config)`)。
   - **True(既定)= 現行挙動を完全維持**(config 省略・空 dict と同一。既存 848 テストは無変更で緑)。
     これは spec-conformance モード=本プロジェクトの現在の性格(契約を正しく実装したことの
     回帰テスト)を維持するための既定。
   - **False = strict 系オーバーライドをスキップ**し、strict 導入前(ADR 0042 まで)の
     観測ベース経路(v1.4/v1.5)へフォールバックする。
2. **規律: 能力評価・対外比較の文脈では `strict_gt_conformance: False` を必須とする。**
   strict ON のまま gt_derive 系 GT に対して測ったスコアは「写し f と f の一致」であり
   能力ではない(ADR 0049)。能力の非循環指標は従来どおり (1) intent 層(t3/scene)、
   (2) 独立ラベラ評価(blind-corpus)に限る。
3. 評価経路の透過: `run_supreme_scenarios`/`build_trace`/`sealeval.run_sealed_evaluation` は
   config をそのまま `run_supreme` へ渡すため追加変更なしで OFF を指定できる。

## ゲート対象の層と根拠(ADR ↔ gt_derive の対応)

| 層 | strict 実装(ON) | 写し元(gt_derive) | 根拠 ADR | OFF のフォールバック先(コード上に残存する旧経路) |
|---|---|---|---|---|
| quality_regime | 生 QoS 規則(≥0.90 GOOD / <0.55 BLOCK / 他 DEGRADED)を core 内でインライン適用 | `quality_regime`(同一閾値・生 QoS) | 0045 | `quality.classify(h_q, vol)`(ADR 0014・HGF h_q/vol 経路) |
| risk_tier | `_risk_tier_strict`: track ゼロでも geom.min_TTC_s を読む・siren salient→danger | `risk_tier`(逐語複製と ADR 0048 が明記) | 0045/0048 | `t0.risk_tier(_t0_tracks(snap))`(track ベース・track ゼロ→安全側 info) |
| t1_state | `_t1_geometry_sequence`: salient(max(w_obs,-r_m))range 軌跡の Δr 規則・pass=最接近直後∧≤8m | `t1_state_seq`(同一構造・同一閾値 _PASS_M/_EPS/_FAR_M) | 0044 | `t1.t1_state`(状態機械)+ v1.5 episode.approach_ratio 補正(ADR 0038) |
| t2_mode | `_mode_seq_strict`: GT の 9 段優先カスケードを逐語複製(quality 再計算含む) | `mode_seq`(逐語複製と ADR 0047 が明記) | 0047 | 段2 logits→`mode.hysteresis`+v1.5 uncertain 上書き(ADR 0015/0039/0040/0042)。t3 窓入力も同じ旧 mode に戻る(strict 導入前と同一のデータフロー) |
| t2_role | `_role_salient`: salient(max(w_obs,-r_m))の種別→role 写像 | `role` + `_salient`(同一規則) | 0046 | `role.classify(_role_evidence(snap))`(evidence 経路・ADR 0017/0028/0029/0034) |
| t2_relation | `_relation_geometry_override`: near/departing/approaching/grouped/unrelated の range 幾何(addressing のみ既存委譲) | `relation_seq`(同一優先順・同一閾値 5/15/0.1m) | 0043 | override 不適用=`relation.classify(_relation_evidence(...))`(4 クラス語彙・ADR 0016) |

**0043/0044 を含める判断**: ADR 0043/0044 は自ら「gt_derive.relation_seq / t1_state_seq の忠実化」
と明記しており、優先順・閾値(near 5m / far 15m / 不感帯 0.1m / pass 8m)が gt_derive の
`_NEAR_M/_FAR_M/_EPS/_PASS_M` と一致する。ADR 0049 の撤回対象にも「ADR 0043-0048」と
明示されている。よって GT 規則の写しに該当し、ゲート対象に含める。
(0043 の addressing 委譲は「逐語コピーを避けた」部分だが、override 全体が relation_seq の
優先カスケードの複製である以上、override 単位でゲートする。)

## ゲート対象外(と、その理由)

- **t0.py 内部の閾値是正(ADR 0045 の risk 部)**: ADR 0045 は `t0.risk_tier` 自体の閾値を
  GT 整合(厳密 `<`・siren→danger)に**その場で書き換え**ており、0045 以前の t0 内部閾値
  (kind 別 caution≤12・siren 下限 caution)はコード上に残っていない。指示の規律
  「新ロジックの発明はしない(旧経路が消えている層はゲート対象外)」に従い、OFF の risk は
  「track ベースの `t0.risk_tier` 経路(=ADR 0048 導入前の core 結線)」までを復元し、
  t0 内部の閾値は現行(0045 是正後)のままとする。
- **t3_hypothesis / scene_regime**: intent 層で GT が f の決定的関数でない(ADR 0049 が能力の
  非循環指標として認めた層)。strict 写しではないためゲートしない。ただし OFF では t3 窓へ
  供給される mode が旧 mode に戻るため、t3 出力は間接的に strict 導入前の挙動へ戻る(意図どおり)。
- **ADR 0038〜0042 の観測ベース改良(v1.5 episode 補正・uncertain 回収・conv link 種別・
  env_start 振動・side_rear routing)**: これらは strict 導入前の経路そのものであり、
  ADR 0049 の撤回対象(0043-0048)に含まれない。OFF のフォールバック先として**残す**。
  (0040/0042 は GT mode_seq の部分近似という性格を持つが、証拠→logit の観測ベース実装で
  あり逐語複製ではない。ゲート境界は ADR 0049 の撤回集合に一致させる。)
- **`fit_supreme`**: 学習サンプル組み立ては従来どおり既定経路(=ON)の view を使う
  (config 非対応・現状維持)。OFF で能力評価する際に学習済み params を併用する場合は、
  この train/infer 差を認識すること(必要になれば別 ADR で config 透過を追加する)。

## 検証

- 既定(ON)の後方互換: 既存 848 テストが無変更で全緑。config 省略・`{}`・明示 True の
  3 形が完全一致(`tests/test_Fbase001_strict_gate.py`)。
- OFF: strict 対象 6 層それぞれに「ON と OFF で出力が異なる決定的 fixture」を用意し、
  OFF 出力が旧経路(t0.risk_tier / quality.classify / role.classify / relation.classify /
  t1 状態機械 / hysteresis mode)に一致することを検証。OFF でも決定的(2 回 run 完全一致)・
  クラッシュなし・8 層 view 形状維持。scene_regime は fixture 群で不変(ゲートの波及が
  strict 系に限られる)。計 11 テスト追加・全 859 passed。

## 帰結

- gt_derive 系コーパスでの再評価は、ON なら「spec-conformance の回帰値」、OFF なら
  「観測ベース実装の値」と**構造的に区別**されるようになった。循環スコアを能力として
  再生させないための実行時の関門が、文書(ADR 0049)に加えてコードに入った。
