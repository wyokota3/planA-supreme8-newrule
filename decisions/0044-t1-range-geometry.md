# ADR 0044(v1.6): t1_state を salient range 軌跡で忠実化(rule_derived 層の移植完成)

- 日付: 2026-06-25
- ステータス: 採用
- 関連: F-006(t1)・ADR 0038(t1 approach_ratio 補正・本 ADR が上書き)・ADR 0043(relation range 幾何)。
- エビデンス: coverage_v2 train/eval(held-out)・coverage_v1(v1.4) も改善・全847テスト緑。

## 背景

t1_state は **0.60** で停滞。relation 同様 t1 も **Tier-A rule_derived = salient range 軌跡の決定的関数**
(`gt_derive.t1_state_seq`)。診断(coverage_v2):

| GT t1 | n(tr/ev) | 旧 acc | 原因 |
|---|---|---:|---|
| pass | 71/30 | **0.03** | approach_ratio~0.4 で approach に誤分類(最接近直後の軌跡特徴が要る) |
| depart | 401/169 | 0.30 | hazard_trend でなく Δr>0(後退)を見るべき |
| approach | 762/316 | 0.55 | approach_ratio<0.3 のフレームが idle に流出 |
| idle | 739/331 | 0.84 | 概ね可 |

ADR 0038 の approach_ratio 補正は**集約 proxy** で、GT の per-frame range 軌跡には及ばなかった。

## 決定

`core._t1_geometry_sequence(snaps)` を追加し、t1 を salient range 軌跡で authoritative に上書き:
- salient track(`w_obs,-r_m` 最大)の range 系列で `Δr<0→approach / Δr>0→depart(最接近直後 ∧ 最接近≤8m→pass)
  / Δr≈0→idle`、先頭は `>15m→idle / 以下→approach`(GT t1_state_seq に一致)。
- salient track が無いシナリオは既存 t1(t1_mod + approach_ratio)に委ねる(後方互換)。
- approach_ratio 補正(ADR 0038)は **salient 在りフレームで本 override に上書きされる**(range 軌跡がより正確)。
- w_obs/r_m は v1.4 入力にも在り version 非依存(観測由来・非循環)。

**規律**: t1 も rule_derived(観測完全可・intent 天井なし)。relation(ADR 0043)と同じく高スコアは
移植完成度を反映し、旧 0.828 の**非汎化な合わせ込みとは別物**(eval=train=1.0 で完全汎化)。

## 結果(train / eval・held-out)

| | TRAIN | EVAL(held-out) | SEAL |
|---|---:|---:|---:|
| t1_state | 0.592→**1.000** | 0.606→**1.000** | 0.598→**1.000** |
| t3_hypothesis | 0.748→0.719 | 0.744→0.718 | 0.738→0.718 |
| **8層平均** | 0.825→**0.872** | 0.826→**0.872** | 0.8241→**0.8719** |

- t1 全4クラス 1.00(train/eval/seal)。**t2_mode は不変**(0.71/0.70)。
- **副作用(正直に)**: t3 が **-0.029**。t1 の正確な `approaching` が mode forward_caution の頻度を変え、
  t3 per-frame fallback(mode 窓依存)が僅かに揺れた。t3 は intent 天井層で、t1 +0.40 に対し純 8 層 +0.048 と
  圧倒的に正の交換。t3 の episode override(approach_ratio 由来)は不変。
- coverage_v1(v1.4)も改善(mean 0.699→0.747)。全847テスト緑(test_F006_t1_v15 を幾何挙動に更新)。

## 限界(正直に)

- t3 副作用 -0.029 は許容(net 大幅正・t3 は intent 天井)。必要なら t3 fallback の mode 窓ロバスト化は別途。
- これで rule_derived 層(risk/t1/role/relation/quality)は出揃い、残るは **t3(0.72)/scene(0.89)= intent 天井層**。
  これ以上は heuristic_confirmed 上限(t3 61%/scene 77%)に律速され、合わせ込みは過適合のため不追求。
