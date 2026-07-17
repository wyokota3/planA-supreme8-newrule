# ADR 0032: t3 traffic_unstable を規則層で forward_caution から生成（学習層の構造欠陥）

- 日付: 2026-06-24
- ステータス: 採用
- 関連: F-009(t3)。ADR 0020(t3 規則層/学習層分担)を一部修正。
- エビデンス: `reports/sealeval-coverage_v1-seal-20260624-improved.md`・**train 内 5-fold lineage-disjoint CV**（seal/eval は最終確認のみ）。

## 背景

t3 の残り負け（seal −0.064）を **research パス**（合成コーパス合わせ込みでなく、train CV で開発・汎化検証）で詰めた。

train CV（seal 非接触）で per-GT-class acc を診断した結果、**4クラスが acc=0.000**（env_start 185 / uncertain_context 181 / traffic_unstable 144 / hazard_declining 53）と判明。これは学習の弱さではなく **「出せないクラス」構造欠陥**（mode/role の空クラスと同型）。

各クラスで supreme が出す mode を見ると:
- **traffic_unstable: 全144件が supreme mode=forward_caution**（baseline §3.9 `_T2_TO_T3`: forward_caution→traffic_unstable と一致）。supreme は traffic_unstable を学習層(conv/traffic/quiet)に委ねていたが、学習層が never 出せず 0.000 だった。
- env_start / uncertain_context / hazard_declining は supreme の mode 空間に **clean な信号が無い**（GT mode の uncertain/env_change を supreme が出せない）。詰めると過適合リスク。

## 決定

**traffic_unstable のみ**、規則層 `_rule_hypothesis` に追加（baseline 忠実）:
`forward_caution 比率 > _RULE_TRAFFIC_RATIO(0.2) → traffic_unstable`（sustained_alert と crowd_tendency の間・baseline 優先順）。
env_start/uncertain_context/hazard_declining は **clean 信号が無いため補完しない**（過適合回避）。

## 結果

- t3 **train-CV: 0.544 → 0.617**（traffic_unstable 0.000→1.000・他クラス無害）。
- t3 **eval(独立 held-out): 0.534 → 0.610**（baseline 0.592 を上回る）。
- t3 **seal: 0.532 → 0.610**（baseline 0.596・**−0.064 LOSE → +0.015 draw**）。
- 8層平均 seal: **supreme 0.5702 vs baseline 0.4782（+0.092）**。
- **弱5＝WIN4 + draw1(t3)・LOSE ゼロ／強3＝全 maintained**＝成功目標を実質達成（全層 supreme ≥ baseline）。全800テスト緑。

## 限界

- env_start/uncertain_context/hazard_declining は依然 0.000（合計 ~419 frames）。supreme の mode 空間に分離信号が無く、規則化は過適合。**真に詰めるには mode の表現力向上 or 実データ拡充（新 held-out 検証）**＝より上流の research。
- t3 は draw（+0.015・δ_strong 内）。intent_derived GT の heuristic_confirmed 61% 近傍が原理 ceiling。
