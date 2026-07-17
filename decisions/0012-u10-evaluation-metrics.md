# ADR 0012: U10(評価指標式)の確定 — baseline 実測方法に接地

- 日付: 2026-06-13
- ステータス: 採用
- 関連: SPEC `U10`/`F-004`/`F-013` 節、ADR 0005(baseline 形式・8層・NA規約差)、ADR 0006(v1.4 語彙)、
  `reports/erroran-20260612-F005.md`、外部クローン `external-data/planA-baseline/`
  (`specs/contracts/N04-EVALUATION.md`=公式メトリクス契約、`scripts/evaluate.py`=実コード)
- 決定者: ユーザー承認済み(2026-06-13・3分岐の決定)

## 背景

U10(評価指標の正確な定義)は F-004(評価ハーネス)/F-013(封印評価)の**最優先ブロッカー**だった。
根拠集めで **baseline の実際の採点コード**(N04-EVALUATION.md の公式定義 + evaluate.py の実コード)が
ローカルクローンに実在することが判明し、指標式を推測でなく**baseline の実測方法に接地**できた。
supreme は baseline と**同一指標式**で測る必要がある(F-013-1)ため、baseline の方法が U10 の基準。
`erroran.py` が per_layer.json と 1e-5 内一致することで採点式は逆算的にも確認済み。

## 決定

### A. 採点方法(baseline 一致・ソースで断定)

- **採点単位 = フレーム単位**。
- **平均法 = micro(global pooling)**: 各層 `Σ正答 / Σ非null`(全シナリオ×全フレームでプール)。macro ではない。
- **正解判定 = 完全一致**(分布は argmax 済みの string ラベルで比較。argmax 同点は sorted 最小キー=evaluate.py `_argmax_key`)。
- **NA/null = 分母から除外**(GT が null のフレームはその層を評価対象外)。
- **層スコア = 8層それぞれの global acc**。**総合 = 8層 global acc の単純平均**(層 macro)。
- **8層** = risk_tier / t1_state / t2_mode / t2_role / t2_relation / t3_hypothesis / quality_regime / scene_regime。
- 連続値の再現判定は ε(U5a)許容、**本採点(8層 acc)は分類完全一致**。

### B. risk_tier 分母 = **210 全採点に統一**(planA evaluate.py 規約)

短尺 T0 の NA 除外特例(外部スコアラの 125)は**採らない**。supreme ハーネスに short-T0 特例を
実装しない。**baseline 参照値は 210 規約で再計測**する(研究者手動・F-013 まで・ADR 0005/0006 の
再計測とセット)。trace.json の risk_tier GT は全210が非null のため 210 採点は機構的に成立。

### C. Anomaly(強い項目)= **採点対象外と確定**

GT 層が存在せず 8層に無い以上、**スコアを作らない**(値を埋めない=F-004 異常系の精神)。
強い項目の維持判定(δ_strong)は **T0(risk_tier)/ T1(t1_state)/ role(t2_role)の3層**で行う。
EPI-NOVEL への紐付け(ADR 0006 候補)は GT 不在のため採らない(新規 GT 作成=U17 隣接の別作業)。

### D. 補助21メトリクス = **参考**(公式採点・勝敗ゲートにしない)

top2_acc / KL / range_mae 等(N04-EVALUATION.md §2)は**報告に併記可**だが、弱い5項目の勝敗・
強い項目維持の判定は**8層 global acc のみ**で行う。SPEC の弱い5項目勝敗(acc 基準)と整合・スコープ最小。

### E. t1_state 採点語彙 = **GT 出現クラスに閉じる**

採点は 4クラス(idle / approach / pass / depart)。契約 enum の stop / repeat は v021 GT に
不出現のため採点クラスから除外する。

### F. quality_regime 語彙 = **v1.4**(GOOD / DEGRADED / BLOCK・ADR 0006)

baseline 参照スコアの **v1.4 再計測が前提**(研究者手動・ADR 0006 で既出・F-013 まで)。

### G. フレーム集計 = **global pooling を公式採点**

層別 `Σ正答 / Σ非null` を公式採点とする。per-scenario score の単純平均は補助(参考)。
短尺/長尺で available_layers が異なる(6 vs 8)ため両者は一致しないが、公式は global。

## 影響

- **U10 ブロッカー解除**。F-004(評価ハーネス)が**フル実装可能**に(F-004-1 採点が定義された)。
  F-013 も指標式が揃う。
- SPEC: U10 を解決済みに更新、ブロッカー注記(残0件)、F-004 のブロッカー注記を更新。
- F-004 実装時: 8層 micro acc(完全一致)+ ε許容の T3 再現判定(F-004-2)+ 指標定義/許容幅
  欠落時の停止(F-004-3)。Anomaly は採点層に含めない。
- **前提作業(研究者手動・F-013 まで)**: baseline 参照スコアの (i) risk_tier 210 規約、
  (ii) quality v1.4 語彙 での**再計測**。これが F-013 の同一土俵比較の前提。

## 追記: 全null層の総合算入(2026-06-13・F-004 実装+監査で確定)

決定A「総合=8層 global acc の単純平均」は**全層が非null前提**の記述。ある層の gt が
全フレーム null(nonnull=0)になる縁ケースの扱いを明文化する:

- **層スコア**: nonnull=0 の層は `NaN`(採点不能)。
- **総合 `overall()`**: **採点できた層(nonnull>0)のみで単純平均**する(NaN 層は平均から除外)。
  採点可能層が1つも無ければ総合も `NaN`。
- 根拠: 本採点データ(catalog 1.4.0・210フレーム)は全GT層が非null のため実運用では発生しない縁ケース。
  0除算回避・他層非波及を満たす穏当な縮退。`reports/audit-20260613-1352-F-004.md` 重点検査A で
  「ADR 未規定の沈黙の裁量埋め・done 非ブロッカー」と評価済み。
- **F-013 着手条件**: 封印評価で全null層が起きうる設計に進む前に、本挙動の妥当性を再評価し
  `overall()` の挙動を固定するテストを追加すること(SPEC F-013 着手条件に登録済み)。

## 残件・申し送り

- **baseline の v1.4 + 210規約での再計測値は未取得**(研究者手動)。U10 は「式」を確定したが
  「baseline 参照値の再取得」は別作業(F-013 まで)。
- U11(統計的有意性)は引き続き別件。勝敗は点推定にとどまる(穴1)。
- 外部スコアラ(N04_architect private repo)の式はクローンに無く未読。8層 acc 式は evaluate.py
  実コードで断定、baseline 列の同式性は catalog の整合検証(±0.01 再現)に依拠した強い推定。
