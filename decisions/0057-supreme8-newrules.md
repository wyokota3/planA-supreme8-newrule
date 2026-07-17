# ADR 0057-s8: supreme8-newrule — 語彙の壁を壊すルール再設計(結果と正直な評価)

- 日付: 2026-07-17 / 基点: planA-supreme7@master
- 決定: mode に uncertain、relation に departing/unrelated を語彙追加。新述語 UncEv/DepEv/FarEv、
  新ルール4本(計29本)、T1 の pass/depart を観測特徴として結線。学習パラメータ 353。

## 検証(coverage_v3/eval 41,810 フレーム)
- 最良構成(基礎6+bilevel 2 の8エポック): 8層平均 **0.6879**(supreme6 0.6874 / supreme2 0.6464)。
  mode 0.6528(+0.0151: uncertain の部分回収)、role 0.9704 維持、relation 0.5785(−0.0043)。
- bilevel を4エポック追加すると mode が 0.530 へ悪化し平均 0.6821(過学習)。既定は8エポック。
- 正直な評価: 語彙上限は撤廃した(理論上限 mode/rel とも 1.0 へ)が、この学習予算・特徴集合では
  新クラスの回収は限定的(uncertain の一部のみ)。departing/unrelated は現特徴(t1_depart・距離)では
  分離が不十分。上限 0.75 超えの実現には、新述語向けの特徴拡充(Δ距離系列・リンク不在の明示)と
  蒸留ターゲット再設計(supreme7 RQ1 の逆転知見)が次の前提となる。
