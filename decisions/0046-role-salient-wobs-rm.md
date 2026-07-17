# ADR 0046: role を GT 整合の salient(w_obs/r_m)種別で確定 — 0.96→1.0

- 日付: 2026-06-26
- ステータス: 採用
- 関連: F-006(role)・ADR 0033(salient_kind/v1.5 salience)・gt_derive.role・planA-baseline ADR-034(同型)。
- エビデンス: coverage_v2 train/eval(held-out)・seal・全847テスト緑。

## 背景

role の GT(`gt_derive.role`)は『最も目立つトラック(`max(w_obs, -r_m)`)の種別』の決定的関数。supreme は v1.5 の
`salience` フィールドで salient を選んでいたが、これが GT 基準(w_obs/r_m)と微妙に食い違い、vehicle 主体の場面で
speech トラックを salient に選ぶ等の副作用で role 0.958(vehicle 0.87 に流出)に留まっていた。

## 決定

`core._role_salient(snap)` を追加し、t2_role を **GT 規則そのもの**で確定:
- salient = `max(w_obs, -r_m)`(トラック順 audio→objects→humans=gt_derive._tracks と同じ・tie 先勝ち)。
- speech→source_speech / vehicle→source_vehicle / siren・alarm→source_alarm / human→(発話で speech 否で human) /
  他 object→source_object / 他→unknown。
- `salience`(v1.5)に依らず w_obs/r_m を使う ＝ v1.4 入力でも同精度(version 非依存)。role_mod.classify 経路は撤去。

## 結果(seal)

| | 旧(v1.5 salience) | 新(w_obs/r_m salient) |
|---|---:|---:|
| t2_role | 0.958 | **1.000** |
| 8層平均 | 0.8995 | **0.9047** |

- train/eval/seal とも role 1.000(オラクル一致)。全847テスト緑。
- role は v1.4 観測層(salience 不要)であることが実装で確定。これで supreme の観測層 follow-up は mode(hysteresis 近似)のみ。
- 比較基準の baseline も同修正(ADR-034)で role 0.571→1.0。結果 baseline 8層 0.9222 が supreme 0.9047 を上回る
  (baseline は mode 1.0・t3 0.694 で勝ち・supreme は scene/relation で勝ち)。観測/集約を正しく実装すれば両系とも高い、を再確認。
