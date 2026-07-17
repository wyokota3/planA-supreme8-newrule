# ADR 0019: F-010 scene 改良 — HGF 階層ボラティリティによる少量学習(計測根拠)

- 日付: 2026-06-13
- ステータス: 採用
- 関連: ADR 0013(scene=少量学習・最有力)、ADR 0018(U4/U24: 学習可能param のみ・k=0.5)、ADR 0006(v1.4 scene 語彙)、
  ADR 0017(独立再実装の流儀)、`reports/erroran-20260612-F005.md`(scene 最弱)、baseline
  `external-data/planA-baseline/src/ns_epi/{scene.py,hgf.py}`、scene 再走計測
- 決定者: ユーザー承認済み(2026-06-13・3問)

## 背景

F-010(scene regime 改良)step1。scene は8層で最弱(acc 0.5286・F-005)。手段は ADR 0013 で少量学習・前提は
ADR 0018(U4/U24)で確定済み。baseline scene を全210フレーム再走(格納値と**100%一致**=計測の健全性確認済み)して
根本原因と学習設計を根拠化した。

## 計測結果(F-005「瞬間差分で判定」を構造で特定)

- baseline scene の `drift = scene_health − 前フレーム scene_health` は**隣接2フレーム差**。診断(H_post 等)が平坦に
  張り付くと drift→0・regime_vol→0 に減衰し、**「持続的に非定常(=CHANGING)」を表す状態変数が存在しない**。
- 誤分類: **CHANGING→STABLE 見逃し30件**(drift≈0・vol≈0 で STABLE 正解と閾値で区別不能)、
  **STABLE→CHANGING/DEGRADING 過敏27件**(drift/vol 大)。両者が drift/vol 軸で重なり**閾値では両立不能**(最良 +2件で頭打ち)。
- **ただし見逃し群は分離可能な別領域**(平坦・中水準 H_post)にあり STABLE 正解との衝突は**1フレームのみ** →
  (水準 + 時間文脈)を同時最適化する**学習分類器**なら原理的に分離余地がある。学習可能 param は全案 ≤11 ≪ 予算105。
- baseline は GT=DEGRADING 30件のうち **3件しか当てていない**(deg 検出が弱い)。

## 決定

### 決定1: アプローチ = 持続性特徴 + HGF 階層ボラティリティ学習分類器

閾値再較正では両立不能と計測で判明したため、**学習**で解く:
- **HGF 3層カーネル**(階層 Gaussian filter)で scene 診断信号(health_raw / H_post)から**潜在水準 μ1** と
  **その変化率・ボラティリティ(層2: log-volatility / 精度 σ)**を階層推定する。**層2のボラティリティが「持続的変化」
  (1ステップ drift が見逃す sustained non-stationarity)を捉える**=見逃しの根本対処。
- **持続性特徴**: nominal 水準からの逸脱(遅い nominal EMA + 逸脱の持続度)を併用。
- **3クラス分類**: (HGF 水準 μ1, HGF ボラティリティ, 持続性)を入力に **STABLE / CHANGING / DEGRADING** を判定。
  **DEGRADING を3クラス目標に含める**(deg 検出も同時最適化)。

### 決定2: 学習可能パラメータ(U24 適合・予算 binding でない)

- 学習対象 = **HGF パラメータ 6個**(κ1,κ2,ω1,ω2,ω3,obs_noise)+ regime 判定の閾値/境界(~3-5個)。計 ~9-11 個。
- U24: 学習可能パラメータのみ計数・k=0.5 → 予算 = 練習用件数(~200)×0.5 ≈ 100。**~11 ≪ 100 で予算は binding でない**。
- 固定の集約重み・EMA α 等を学習に含めるかは実装時に確定(含めても予算内)。

### 決定3: 学習(fit)は決定的手順

- HGF param + 閾値を**練習データ上で決定的に fit**(grid / 座標降下等・乱数なし)。再現性(F-004-2)のため学習も決定的。
- 実際の学習値は実装の学習実験で決まる(step1 では構造・特徴・学習対象を確定)。

### 決定4: スコープ = scene モジュール(HGF カーネル + 特徴 + 分類器)を独立実装

- supreme が **HGF カーネルを独立再実装**(baseline/external を import しない・F-006 と同じ独立性の流儀)。
  HGF は quality/anomaly/scene が使う共有基盤だが、F-010 が最初に実装する(将来再利用可)。
- 診断信号の抽出(6診断 → health_raw)は上流の共有基盤(スコープ外・入力として与える)。
- 語彙 v1.4: STABLE / CHANGING / DEGRADING。

## 影響

- F-010 は supreme の scene モジュール(独立 HGF + 持続性 + 3クラス分類 + 決定的 fit)を実装。テストは
  HGF フィルタの決定性(既知 param + 入力列 → belief 更新)・持続性特徴(平坦・非nominal → 持続逸脱検出)・
  3クラス分類(featue+param → regime)・**学習可能 param ≤ data×0.5**・fit の決定性 を固定。
- 受け入れ条件 F-010-1(F-013 で項目別対比が測定・報告)は F-013 で測定(改良は成功目標)。
- HGF カーネルは共有基盤として今後 quality(h_q/vol)・anomaly でも再利用可能(F-013 の end-to-end に資する)。

## 残件・申し送り

- **実際の学習値**(fit 後の HGF param・閾値)は実装の学習実験で決定。最終的な scene acc 改善は F-013 で測定(成功目標)。
- **DEGRADING 再現と過敏の trade-off** は学習の目的関数設計で扱う(GT 30件・baseline 3/30)。同時最適化の目的関数は実装時に確定。
- 見逃しと過敏の同時分離は**学習器が同時最適化**することで実現を狙う(手格子では未発見・計測上は分離余地あり=衝突1件)。
- HGF カーネルの独立再実装(層数・更新式・初期 belief)は既知アルゴリズム。supreme 内に閉じる(F-006-2 と同じ独立性)。
- baseline scene は HGF カーネル不使用(EMA)だったが、supreme は本格 HGF を採用(ユーザー決定)。
