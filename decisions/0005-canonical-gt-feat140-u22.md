# ADR 0005: 正準GTを feat 1.4.0 に改ピン + U22(baseline 結果形式)の解決

- 日付: 2026-06-12
- ステータス: 採用
- 関連: `specs/GT_SCHEMA.md`(改版)、`specs/SPEC.md`(外部参照/F-001/U22)、ADR 0003(初版ピン)、F-005 ステップ1

## 背景

F-005 着手時の U22 実地調査(`planA-baseline.git` @ `ddb1b97` をクローン)で次が判明した:

1. **baseline 結果の形式は良好**: `results/trace/trace.json` にフレーム単位の予測(view)+正解(gt)が
   8層×210フレームで格納されており、クラス別誤り分析(混同行列)が直接作れる。集計値
   (`per_layer.json`/`per_scenario.csv`)と測定手順書(`baseline-catalog-1.4.0.md`)も揃う。
2. **GT のバージョン分岐**: baseline は `N04-scenario-contract` の **feat/ns016-020-role-relation-gt
   @ `a0b8822`(catalog 1.4.0)** の GT で測定されている(全20ファイルのハッシュ一致を確認)。
   一方 ADR 0003 でピン留めした **main @ `de77b04`(catalog 1.3.0 表記)** は、
   (a) t2.mode 語彙が異なり(main: side_rear_caution/uncertain ⇔ feat: alert_observation/conv_participation)、
   (b) ns016-020 の role/relation GT を持たず、
   (c) quality_regime の改訂(GOOD/DEGRADED/BLOCK 順位シフト)を含む。
   **main と feat は相互に取り込まれていない分岐**であり、どちらも他方の上位互換ではない。
3. このままでは GT_SCHEMA(main 由来の mode キー集合)が baseline の GT を**拒否**し、
   エラー分析の語彙と開発GTの語彙がズレる。

## 決定(ユーザー承認済み)

**supreme の正準GT(練習用データ・GT_SCHEMA の基準)を feat 1.4.0(@ `a0b8822`)に改ピンする。**

- 理由: baseline 測定と同一土俵(プロジェクトの核心原則)。エラー分析(F-005)の誤り定義と
  改良モジュール(F-007〜011)の開発語彙が一致する。
- main の quality_regime 改訂は取り込まない。将来 feat→main がマージされた時点で再ピンを検討
  (その際は baseline の再採点=研究者の手動運用とセットで行うこと)。
- 却下: main 採用(語彙ズレ3点の注記管理が常時必要)/ リポジトリ整理待ち(F-005 が無期限ブロック)。

## 影響

- `specs/GT_SCHEMA.md`: 導出元を feat @ `a0b8822` に変更。**t2.mode のキー集合を改訂**
  (side_rear_caution/uncertain を廃し alert_observation/conv_participation を追加。他5分布は不変)。
- **F-001 への波及**: `tests/fixtures_gt.py`・mode キー集合に依存するテスト・`src/supreme/datagov.py` の
  クラス集合定数の更新が必要(本ADR直後に実施)。
- `specs/SPEC.md`: 外部参照に baseline 結果のピン(`ddb1b97`)を追加、シナリオのピンを feat に変更、
  U22 を解決済みに更新。
- U22 解決により残ブロッカーは U7(契約中身の精査)/ U10(指標定義)の2件のまま変わらず。

## 記録事項(F-005 以降のための観測)

- 評価は **8層**で Anomaly 層は存在しない(GT にもフィールド無し)。SPEC の「強い項目」の Anomaly の
  扱いは U10 で確定が必要。
- risk_tier の NA 規約差: 外部スコアラは短尺 T0 を NA 除外(非null=125)、planA `evaluate.py` は
  全210で採点。U10 で吸収すること。
- catalog 1.4.0 の baseline 8層スコア(=supreme が項目別に挑む基準値の最新参考。封印再計測値ではない):
  risk_tier 0.9040 / t1_state 0.9095 / t2_mode 0.5714 / t2_role 0.8429 / t2_relation 0.5571 /
  t3_hypothesis 0.6286 / quality_regime 0.6667 / scene_regime 0.5429。
  弱い5項目(mode/relation/T3/scene/quality)・強い項目(T0/T1/role)の分類は最新値でも維持される。
