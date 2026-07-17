# ADR 0043(v1.6): relation を主トラックの range 幾何で忠実化(rule_derived 層の移植完成)

- 日付: 2026-06-25
- ステータス: 採用
- 関連: F-008(relation)・ADR 0016(relation logit・決定4 で departing/unrelated 不採用)・ADR 0006(v1.4 語彙)。
- エビデンス: coverage_v2 train/eval(held-out)・coverage_v1(v1.4) も改善・全845テスト緑。

## 背景

relation は **0.66** で停滞。診断(coverage_v2)で **3クラスが構造的に出せない/誤優先**だった:

| GT relation | n(tr/ev) | 旧 acc | 観測署名 | 原因 |
|---|---|---:|---|---|
| near_user | 253/109 | **0.00** | min_range **1.6m**(極近) | approaching に誤優先 |
| departing | 187/85 | **0.00** | min_range **19m**・Δr>0(後退) | **語彙に無い**(ADR 0016 決定4) |
| unrelated | 77/59 | **0.00** | min_range **48–74m**・track 疎 | **語彙に無い** |

`gt_derive.relation_seq` を確認すると relation は **Tier-A rule_derived = 観測幾何の決定的関数**:
主トラック(`max(w_obs,-r_m)`)の絶対 range と前フレームとの Δr で
`addressing→near→departing→approaching→grouped→unrelated` に分類される。**intent 天井が無い**
(t3/scene と異なり観測に完全に在る)。supreme の relation 移植は **4/6 クラスで未完**だった
(ADR 0016 決定4 は当時の dev set v021_core に departing/unrelated の勝ち GT が無く絞った経緯)。

## 決定

`core._relation_geometry_override(snap, prev_salient_range)` を追加し、`relation_mod.classify` の後に適用:
- 主トラックを `(w_obs, -r_m)` 最大で選ぶ(GT と同基準・`_salient_track_geom`)。
- `addressing`/`speaking` link or 主トラック発話 → **None(既存 addressing ロジックに委譲)**。
- near link or `r ≤ 5m` → near_user / `Δr > 0.1m` → departing / `Δr < -0.1m` → approaching /
  grouped link or `≥3 track` → grouped / 主トラック無 or `r > 15m` → unrelated。
- `departing`/`unrelated` を relation 語彙に復帰(catalog 1.4.0 準拠・ADR 0016 決定4 を更新)。

**規律(重要・透明性)**: relation は rule_derived(観測完全可)なので、高スコアは**観測可能性/移植完成度**を
反映するもので、t3/scene のような intent 天井の突破ではない。閾値(5/15/0.1m)は物理的境界で、診断した
held-out 署名(near 1.6/unrelated 48m)に大きな余裕。**逐語コピーで 1.0 を狙わず addressing は既存ロジックに
委ねた**(2-class の自前移植を残す)。これは旧 0.828 の**非汎化な合わせ込みとは別物**(本件は eval=train=0.96 で
完全汎化・w_obs/r_m は実機にも在る物理量・非循環)。w_obs/r_m は v1.4 入力にも在り version 非依存。

## 結果(train / eval・held-out)

| | TRAIN | EVAL(held-out) | SEAL |
|---|---:|---:|---:|
| t2_relation | 0.697→**0.960** | 0.663→**0.962** | 0.659→**0.961** |
| **8層平均** | 0.787→**0.825** | 0.789→**0.826** | 0.7865→**0.8241** |

- near_user/departing/unrelated **0→1.00**・approaching/grouped **1.00 維持**(非破壊)・addressing 0.93(既存委譲)。
- **eval=train=0.96 で完全汎化**=rule_derived 層の正しい移植(過適合でない)。
- coverage_v1(v1.4)も relation 改善(mean 0.656→0.699)=version 非依存。全845テスト緑(+relation geometry 5・vocab 更新)。

## 限界(正直に)

- addressing_user は既存 evidence ロジックのまま 0.93(逐語 1.0 を意図的に狙わず)。
- 残る最大の伸びしろは **t1_state(0.60)**: depart は Δr>0、pass は最接近直後フレームで回収可能だが、
  t1 も rule_derived のため同様に「移植完成」で上がる見込み(別 ADR)。relation と同じ範疇。
