# ADR 0053-s4: supreme4 — NeuPSL の学習・推論を最新研究の技法で強化する

- 状態: 採用
- 日付: 2026-07-16
- 基点: planA-supreme3@master(d4f6b35)。T2=NeuPSL・T2 以外は supreme2/3 と同一という
  不変条件を継承する。
- 根拠文献: NeuPSL(IJCAI 2023, arXiv:2205.14268 付録E.1)/ NeSy-EBM(arXiv:2407.09693)/
  Convex &amp; Bilevel NeSy(ICML 2024, arXiv:2401.09651)/ HL-MRF &amp; PSL(JMLR 2017)/
  margin-rescaling の失敗モード(AISTATS 2016, arXiv:1510.06002)/ PSL 公式イディオム(cora.psl)。

## 決定(supreme3 からの変更点)

1. **二乗ヒンジ(p=2)+ ε‖y‖² Tikhonov(ε=0.005)** — ポテンシャルを w·max(ℓ,0)² に変更。
   winner-take-all を按分挙動に変え(JMLR 2017 §3.1.3)、MAP を一意化して学習勾配を安定させる
   (ICML 2024)。
2. **コスト感応マージン** — 一律マージン(margin-rescaling)は「易しい層がマージン予算を占有し
   他層が飢餓する」既知の失敗モード。マージン係数を「基準 0.6 × 層別クラス逆頻度(train から算出・
   [0.25,4] クリップ)」の変数別係数に置換。supreme3 で観測した mode 劣化の直接治療。
3. **ニューラル述語のラベル蒸留事前学習 → joint は極小 lr** — 各 MLP を GT 由来の述語ターゲット
   (例: SpeechSrc ← role=source_speech)で BCE・full-batch 250 步・不均衡補正つきで事前学習し、
   joint の lr_n は 0.006(NeuPSL 引用NWの「事前 lr ≫ joint lr」手順・SATNet の接地監督の教訓)。
4. **ルール重みの単体制約+正規化指数勾配+log バリア** — クリップ [0,8] を、総質量固定
   (Σ初期重み)の単体上の指数勾配更新(λ=1e-3 の −log w バリア付き)に置換(IJCAI 付録 E.1 の
   崩壊解対策)。
5. **クラス別負事前** — ⊤→既定クラスの3ルールを廃し、全19クラスに学習可能な負事前
   (E += p_c·y_c²、既定クラス初期値 0.01・他 0.08・上限 0.5)を導入(cora.psl の
   `0.001: !HasCat ^2` + functional 制約イディオム。functional は既存の単体射影が担う)。
6. **warm-start** — 学習中の loss-augmented MAP を前エポックの解から温間開始(ICML 2024)。
   学習可能パラメータは 176(ルール25+負事前19+MLP132)。

## 検証(2026-07-16・coverage_v3: train 2,000×10ep / eval 8,600・41,810 フレーム・strict OFF)

| 層 | supreme2(手調整) | supreme3 | supreme4 | s4 − s2 |
|---|---:|---:|---:|---:|
| t2_mode | 0.6637 | 0.4314 | 0.6291 | −0.0345 |
| t2_role | 0.6067 | 0.6929 | **0.8861** | **+0.2793** |
| t2_relation | 0.5851 | 0.5599 | 0.5599 | −0.0252 |
| t3(下流) | 0.4733 | 0.3524 | 0.4665 | −0.0068 |
| **8層平均** | 0.6464 | 0.6099 | **0.6730** | **+0.0266** |

- **supreme4 は supreme2(手調整ルール)を 8層平均で上回った初の学習系**。T2 micro は
  0.619 → 0.692。role の +0.279 は事前学習された HumanSrc/ObjSrc 述語が
  source_human/source_object を取れるようになったことによる。
- T2 以外の4層(risk/t1/quality/scene)は supreme2 と全フレーム完全一致(不変条件の全量実証)。
  ガード: 学習 0.7816 ≫ 事前 0.3533。テスト: 主要スイート緑(param 数テストは 176 に更新)。
- 残課題: relation(−0.025)と mode(−0.035)。GT ラベル uncertain は語彙外のため両者とも
  原理的に不正解(共通の上限)。GT は規則生成のため本結果は「仕様規則への汎化」であり、
  能力の主張には独立ラベラ評価が必要(ADR 0049 の規律を継承)。
