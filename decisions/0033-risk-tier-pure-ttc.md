# ADR 0033: risk_tier を kind 非依存の純 TTC ルールへ（coverage_v1 GT 整合）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-006(T0)。ADR 0017 決定3 T0(kind 別閾値)を上書き。**supreme のみ**(baseline は read-only で不変)。
- エビデンス: `reports/sealeval-coverage_v1-seal-20260624-improved.md`・train 相関分析・eval/seal 確認。

## 背景

risk_tier は coverage_v1 で 0.52(v021_core では 0.90)。両モデル同一入力で同値=入力アダプタの欠陥ではなく、**モデルの risk 規則とコーパス GT 導出の不一致**。train で GT risk と min_TTC_s を相関付けると、GT は **min_TTC_s だけの決定的関数**だった:

| min_TTC_s | GT risk |
|---|---|
| ≤ 2 | danger(554/554=100%) |
| 2〜5 | caution(65/65=100%) |
| 5〜12 | caution(95%) |
| >12 / None | info(90%超) |

すなわち GT は **「ttc≤2→danger / ≤12→caution / それ以外 info」の kind 非依存・純 TTC ルール**(ADAS で標準的な TTC 基準の衝突リスク)。一方モデルは kind 別閾値(alarm=caution 5・speech=2…v021_core 手調整・baseline 流用)で、alarm が ttc=8 のとき GT=caution・モデル=info と系統的にズレていた(caution→info 260件・danger→caution 128件)。

## 決定

t0 の `_THRESHOLDS` / `_DEFAULT_THRESHOLDS` を **全 kind (caution=12, danger=2) に統一**(`_t0_tracks` は全 track に ttc_s=min_TTC_s を与えるため、これで GT 純 TTC ルールと一致)。

- ユーザー判断で採用(「supreme の絶対値を上げる」)。純 TTC は kind 別手調整より一般的・原理的。
- **supreme のみ**変更。baseline は read-only の参照実装で改変不可(=固定の基準)。
- 強い項目「baseline 流用で死守」の設計を、本層では coverage_v1 GT 整合へ意図的に変更。
- t0 ユニットテスト7件を新閾値の契約へ更新(`tests/test_F006_t0_risk_tier.py`)。全800緑。

## 結果(seal 真値・86件)

| 層 | 前(ADR 0032後) | 本 ADR 後 |
|---|---:|---:|
| risk_tier | 0.5245(=baseline) | **0.9387(+0.414)** |
| t2_mode | 0.3113(+0.135) | **0.4730(+0.297)** |
| t3_hypothesis | 0.6103(+0.015 draw) | 0.5172(**−0.078 LOSE**) |
| 8層平均 | 0.5604(+0.082) | **0.6305(+0.152)** |

総合 **0.5702→0.6305(+0.060)**。risk+0.41・mode+0.30(risk→mode 連動)が t3−0.09 を大きく上回る。

## トレードオフ・限界(正直に)

- **t3 が draw→LOSE(−0.078) に回帰**: risk を正しく danger にすると、会話エピソード中の衝突危険フレーム(GT t3=conv_participating ∧ GT risk=danger=380件)が正しく mode=emergency になり、t3 が会話 intent を mode 窓から復元できず sustained_alert に落ちる。これは t3 の既知天井(intent_derived・mode→t3 ボトルネック)であり、**intent ラベルへの t3 合わせ込み回避**のため復元しない。
- **t1_state は未変更**: GT t1≈軌跡 dynamics(range 推移)由来で、risk のような単一 clean 信号が無い。idle→approach 163件は ttc<12 の静的 approach 閾値 vs 軌跡 dynamics の不一致だが、合わせるには dynamics 検出の再設計(合成軌跡への過適合)が要るため触らない。
- **純 TTC は coverage_v1 GT レシピへの整合**でもある(閾値 2/12 はこのコーパス由来)。実世界の risk が kind 依存しうる点は別問題。新 held-out / 実データでの再検証が望ましい。
