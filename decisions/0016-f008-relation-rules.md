# ADR 0016: F-008 relation 改良 — addressing 発火条件の再設計 + grouped 較正(計測根拠)

- 日付: 2026-06-13
- ステータス: 採用
- 関連: ADR 0013(U1: relation=ルール改良)、ADR 0006(v1.4 語彙)、
  `reports/erroran-20260612-F005.md`(relation 誤り・配線漏れ仮説 棄却)、baseline
  `external-data/planA-baseline/src/ns_epi/t2.py`(relation 判定)、relation 再走計測2回
- 決定者: ユーザー承認済み(2026-06-13・2問)

## 背景

F-008(t2_relation 改良)step1。手段は ADR 0013 で「ルール改良(addressing 発火条件・優先度の再設計
＋欠落クラス追加)・配線追加ではない」と確定済み。baseline relation ロジック(t2.py の logit 5箇所・
4クラス)を読み、全210フレーム再走(格納値と**100%一致**=計測の健全性確認済み)して根拠化した。

## 計測結果(F-005 の relation 診断を覆す)

- **F-005 主因(a)「優先度で near_user に劣後」は不正確**: GT=addressing_user の**全30フレームで
  call_user/linked_addressing=0**(データセット全210で該当証拠が皆無)→ addressing logit は一度も発火せず。
  優先度競合ではなく**addressing 証拠が入力に存在しない**。addressing と near_user は入力分布が重複し
  **入力で分離不能**(user 指向の識別子が PSO 入力に無い)。
- **approaching↔grouped 18件**: GT=approaching→grouped 9件は全件 approaching 入力=False(**上流 T1 の
  接近検知漏れ**・relation 層に信号無し)。GT=grouped→approaching 9件は grouped 無証拠既定 vs approaching。
- **departing/unrelated**: 6クラスGTに存在するが確率は一律0.04フロアのみ・**argmax で一度も1位にならず
  誤りを0件しか生まない**(語彙追加の是正0件)。
- **grouped 既定弱化は破滅的**: 多数派 grouped(118/210)の大半が無証拠既定(ルール5)依存。既定 drop で
  103件を失う(計測)。**既定は保全し、むしろ強化する方向が有効**。

## 決定

### 決定1: F-008 のスコープ = relation の logit ルール(証拠抽出は上流)

F-008 = supreme relation の**logit ルール(relation 証拠 → relation logit → argmax)**。PSO 入力からの
証拠抽出(段1)は上流の共有基盤=スコープ外。relation 語彙は v1.4(addressing_user/near_user/approaching/
grouped。departing/unrelated は本 benchmark で勝ち GT が無く是正0のため追加しない)。

### 決定2: addressing 発火条件の再設計(計測根拠)

call_user 証拠が入力に皆無なので、利用可能な証拠で addressing を発火させる:
- **新ルール: `near_prox(min_range<3m) ∧ speaking_link≥1` → addressing_user += 2.5**。これにより
  near_user(+1.5)より addressing(2.5)が優先される(配線追加ではない=speaking link は既存・発火条件の再設計)。
- 既存の `call_user ∨ linked_addressing>0.3 → addressing += 2.5` も保持(将来 call_user 証拠が入る入力で有効)。
- 計測: 是正25/副作用10(near_user 5・grouped 4・approaching 1)。**near_user 5件は addressing/near_user が
  入力分離不能ゆえの既約な曖昧性**(GT 自身が near+speaking の25/30を addressing とラベルしており GT 意図に整合)。

### 決定3: grouped 較正(B1 + 既定強化)

- **B1: `multiple_humans(humans≥2)` → grouped += 2.0**(grouped に正証拠を与える)。
- **既定強化: 無証拠既定 grouped を 1.0 → 2.0**(EMA持ち越し型の grouped→approaching 振動を回収)。
- 計測: 併せて grouped を約6件是正(approaching を巻き込まない w=2.0 が最適点。w≥2.5/3.0 は approaching を割る)。

### 決定4: approaching→grouped 9件(上流 T1)・departing/unrelated は F-008 スコープ外

- **GT=approaching→grouped 9件は relation 層で原理的に取れない**(approaching 入力=False=上流 T1 の
  approach 判定漏れ)。**T1(F-006/t1 改良)側の課題として申し送る**。
- **departing/unrelated** は勝ち GT が無く是正0のため**語彙追加しない**(将来データ/安全要件で再評価・申し送り)。

## 影響

- F-008 は supreme relation の logit ルール(addressing 再設計 + grouped 較正)を実装。テストは合成
  relation 証拠 → 期待 relation label で、計測根拠ケース(near+speaking→addressing 優先、multiple_humans→
  grouped、無証拠既定→grouped 強化、approaching の保全)を固定。
- 推奨構成での計測見込み: **acc 0.748→0.838(+19件)**。是正30(addressing 24 + grouped 6)/副作用11。
- 証拠抽出(段1)は F-008 スコープ外(上流共有基盤)。F-013 の end-to-end には上流が要る。
- 受け入れ条件 F-008-1(F-013 で項目別対比が測定・報告)は F-013 で測る。

## 残件・申し送り

- **approaching→grouped 9件 = 上流 T1 の approach 判定漏れ**(relation 層で解決不能)→ T1 改良の別課題。
- **departing/unrelated = 勝ち GT ゼロ**(語彙追加は将来データ/安全要件で再評価)。
- **addressing/near_user は入力で分離不能**(user 指向の識別子が PSO 入力に無い)。完全分離には**入力契約の
  拡張**が要る(別課題・near_user 5件の既約曖昧性として受容)。
- 証拠抽出基盤(段1)の supreme 実装は未着手(上流共有基盤・mode/relation 共通)。
- logit 重み(2.5/2.0)は baseline/planA 計測値。supreme 独立実装後の分布で最終確認(F-013・成功目標)。
- EMA/softmax 平滑化は baseline 由来。F-008 は logit ルールのみ(平滑化は上流/別扱い)。
