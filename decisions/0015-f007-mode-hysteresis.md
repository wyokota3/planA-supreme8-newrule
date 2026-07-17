# ADR 0015: F-007 mode 改良 — 安全優先の局所ヒステリシス(計測根拠)

- 日付: 2026-06-13
- ステータス: 採用
- 関連: ADR 0013(U1: mode=ルール改良・閾値再較正/ヒステリシス)、ADR 0006(v1.4 mode 語彙)、
  `reports/erroran-20260612-F005.md`(mode 過剰遷移・境界振動)、baseline
  `external-data/planA-baseline/src/ns_epi/t2.py`(mode 判定)、h_q 同型の mode 再走計測
- 決定者: ユーザー承認済み(2026-06-13・2問)

## 背景

F-007(t2_mode 改良)step1。手段は ADR 0013 で「ルール改良(閾値再較正・ヒステリシス)」と確定済み。
baseline mode ロジック(t2.py の5段: 証拠抽出→ルール logit→温度softmax→EMA→argmax)を読み、
mode を全210フレーム再走(格納 posterior と**最大差0・argmax 不一致0**=計測の健全性確認済み)して
再較正を根拠化した。

## 計測結果(静的仮説を一部覆す)

- **baseline mode にヒステリシスは無い**(logit 計算は前フレーム mode を参照しない)。quiet_standby は
  「全 mode logit=0」の無証拠既定で、`new_entity→env_change+2.0`・`has_siren→emergency+2.5`・
  `low_quality→conv+2.0` 等が**単一フレームで加点**するため、わずかな証拠で quiet が即負ける(過剰遷移)。
- **過剰遷移32件の機構別内訳**: new_entity→env_change(10) / speech→conv_ongoing(9) / siren→emergency(8) / 他(5)。
- **F-005 の「隣接境界の振動」仮説は不正確**: `forward_caution→alert_observation`(9件)は全件 side_rear=True の
  **角度ゲートによる構造的排他=ラベル意味論の不一致**(閾値で解けない)。`forward_caution→emergency`(7件)は
  全件 siren=True で、サイレンを弱めると真の emergency 取りこぼし(安全リスク)。

## 決定

### 決定1: F-007 のスコープ = 局所ヒステリシス層(証拠→logit 生成は上流)

F-007 = supreme mode の**局所ヒステリシス層**。入力 = フレームの mode logit 群 + **前フレーム argmax mode**、
出力 = ヒステリシス適用後の mode。証拠抽出→ルール logit の生成(baseline t2.py の段1-2 相当)は**上流の共有基盤**で
F-007 スコープ外(F-011 で観測式+HGF を上流としたのと同型)。mode 語彙は v1.4(10クラス・ADR 0006)。

### 決定2: 安全優先の局所ヒステリシス(emergency/alert_required は除外)

- **前フレーム argmax == quiet_standby のとき**、各「遷移先 mode(≠quiet_standby)」の logit を **block=2.6 減衰**
  してから argmax。これにより単一フレームの弱い証拠での過剰遷移を抑える。
- **安全クリティカルな mode(emergency / alert_required)は減衰しない=即発火**(ハザード警報を遅延させない)。
- **前フレーム argmax ≠ quiet_standby のときは減衰しない**(計測した機構は quiet からの過剰遷移抑制に限定)。
- 前フレーム argmax のみ参照する**局所機構**(エピソード状態を持たない)= T3(F-009)と非干渉(ADR 0013 制約)。
- 計測根拠(baseline mode acc 0.6238=131/210 基準・siren 除外変種): **是正13・副作用8・純増+5・acc → 0.648**。
  副作用8件は**全て真の遷移 onset の1フレーム遅延**(ヒステリシスの本質的トレードオフ)。

### 決定3: 隣接境界群は F-007 スコープ外(ラベル意味論)

`forward_caution↔alert_observation`(9件・side_rear 角度ゲート)と `forward_caution→emergency`(7件・siren)は
**ラベル意味論/安全方針の問題で閾値再較正では解けない**(F-011 の DEGRADED→BLOCK と同型)。GT 定義
(側後方接近=どちらの mode か)と近接サイレンの安全方針の**別課題として申し送る**(F-007 スコープ外)。

## 影響

- F-007 は supreme mode の局所ヒステリシス層を実装。テストは合成 `(logits, prev_mode)` → 期待 mode で、
  「prev=quiet で良性遷移を block=2.6 抑制」「emergency/alert_required は抑制しない(即発火)」
  「prev≠quiet で不変」を固定。
- 証拠→logit 生成(段1-2)は F-007 スコープ外(上流共有基盤)。F-013 の end-to-end には上流が要る。
- 受け入れ条件 F-007-1(F-013 で項目別対比が測定・報告)は F-013 で測る。

## 残件・申し送り

- **隣接境界群(side_rear 9・siren 7)= ラベル意味論/安全方針の別課題**(GT 定義・近接サイレンの扱い)。
- **カスケード限界**: 局所1フレームヒステリシス(prev argmax のみ)は、baseline の EMA 平滑化と連鎖して
  持続遷移を吸収しうる。回避には確認カウンタ等の最小状態が要るが、それは T3(F-009)のエピソード状態保持と
  責務が触れるため**本 ADR では持ち込まない**(ADR 0013「局所に留める」制約)。既知限界として記録。
- **証拠→logit 生成基盤**(段1-2・PSO 入力からの特徴抽出)の supreme 実装は未着手(上流共有基盤)。
- block=2.6 は baseline/planA での計測値。supreme 独立実装後の logit 分布で最終確認(F-013・成功目標)。
- baseline 参照スコアの v1.4・再計測(研究者手動・F-013 まで)。
