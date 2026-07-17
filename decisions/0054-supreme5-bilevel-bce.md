# ADR 0054-s5: supreme5 — bilevel BCE(minimizer-based 損失)による微調整段

- 状態: 採用 / 日付: 2026-07-16 / 基点: planA-supreme4@master(0e72f66)
- 根拠: NeSy-EBM(arXiv:2407.09693)の minimizer-based 損失と双レベル値関数最適化。
  実証では値ベース(構造化パーセプトロン)比で最大 +7pt(Cora 74.16→81.07)。
  著者ら推奨の「値ベースで事前学習 → minimizer-based で微調整」の2段構成に従う。

## 決定

`neupsl.fit_bilevel` を追加: min_{w,ŷ} BCE(ŷ, GT) + μ·max(M_ρ(ŷ; w) − V(w), 0)² を
交互降下で解く簡略実装。M_ρ は Moreau 包絡(prox は E + (1/2ρ)‖·−ŷ‖² の MAP・
warm-start)、∇_ŷM = (ŷ−prox)/ρ、重み勾配は包絡定理より μ·2·pen·(Φ(prox)−Φ(y*_free))。
学習手順: エポック1〜8 = supreme4 レシピ(値ベース)→ エポック9〜10 = bilevel 微調整。
パイロットで MLP も更新すると mode が劣化(0.866→0.673)したため、bilevel 段は
**MLP 凍結(lr_n=0)・保守設定(lr_w=0.08, lr_y=0.2, μ=1.0, ρ=0.6)**のシンボリックのみ
更新とした(NeSy-EBM の Modular 学習に相当)。決定的(乱数・時刻なし)。

## 検証(coverage_v3: train 2,000 / eval 8,600・41,810 フレーム・strict OFF)

| 層 | supreme2 | supreme4 | supreme5 |
|---|---:|---:|---:|
| t2_mode | 0.6637 | 0.6291 | 0.6380 |
| t2_role | 0.6067 | 0.8861 | **0.9704** |
| t2_relation | 0.5851 | 0.5599 | 0.5599 |
| t3(下流) | 0.4733 | 0.4665 | 0.4654 |
| **8層平均** | 0.6464 | 0.6730 | **0.6846** |

bilevel 微調整は role +0.084・mode +0.009 を上積みし、系列最高の 0.6846(supreme2 +0.038)。
T2 以外4層は supreme2 と全フレーム一致(不変条件)。ガード: 学習 0.8237 ≫ 事前 0.3533。
残課題: relation(0.5599 で停滞・GT 語彙 departing/unrelated が語彙外)と mode(−0.026)。
GT は規則生成のため本結果は仕様規則への汎化であり、能力主張には独立ラベラ評価が必要。
