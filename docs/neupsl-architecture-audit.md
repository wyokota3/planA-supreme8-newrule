# NeuPSL architecture 図解 — 監査 (draw-neupsl-architecture skill step 6)

対象: `docs/architecture-explainer.html` ③節の図解差し替え(旧「NeuPSL 共通基盤」3要素 →
図(a)推論アーキテクチャ 6ゾーン + 図(b)学習 3段交互 + 凡例)。
source of truth: `docs/neupsl-architecture-spec.yaml`。
証拠元: `src/supreme/neupsl.py`・`src/supreme/core.py`・
`reports/situations_v1-eval-20260722/run_supreme_situations.py`(N3 レシピの配線のみ)。

## 1. 前提と方針

- 「実装コードを真実とする」(skill: prose より executable code を優先)。ドキュメントとコードが
  食い違う場合はコードに従い、食い違い自体を本監査に記録した。
- 図には確証のある事実のみを出し、学習後の重み・MLP パラメータ値は決定的だが図示せず TBD とした。
- 図(a)は推論(実行時)、図(b)は学習に厳密に分離。単一の逆伝播矢印は描かない(交互3段)。
- レンダラ `scripts/render_architecture.py` は**検証**に使用(spec を validate、mermaid/dot/svg/pdf/png を出力)。
  出力は Graphviz(`font-family="Arial"`・固定ライト配色・ダーク非対応)で、テーマ対応の当解説と不整合
  かつ日本語描画が Arial 依存になるため、**成果図は手書きインライン SVG**(ページの CSS 変数で light/dark
  両対応・currentColor/形状で役割区別)にした。これは skill の許容(「renderer の SVG が醜ければ手書き」)に沿う。

## 2. 証拠表 (evidence ledger — すべて confirmed)

| 主張 | 状態 | 証拠 (file:line) |
|---|---|---|
| ニューラル述語 12個(9原型 + UncEv/DepEv/FarEv) と入力特徴キー | confirmed | `neupsl.py:63-76` |
| 各述語 MLP: 入力 d(1-4) → 隠れ H=5(tanh) → sigmoid、b2=-2.0、決定的 sin 初期化 | confirmed | `neupsl.py:56, 84-105`, `_dseq 36-42` |
| 述語別入力次元 d(ConvEv3/AddrEv4/SpkOnly2/CrowdEv2/NearEv2/SpeechSrc3/HumanSrc3/ObjSrc3/LowQ1/UncEv4/DepEv3/FarEv4) | confirmed | `neupsl.py:63-76` |
| 観測述語 14個(OBSERVED) | confirmed | `neupsl.py:79-81` |
| ルール総数 29本(mode10+role6+rel4+層間4+新語彙4+持続1) | confirmed | `neupsl.py:133-169` |
| 代表ルール r_danger_emerg w5.0 risk_danger→Mode(emergency) | confirmed | `neupsl.py:135` |
| 代表ルール r_conv_ongoing w4.0 ConvEv→Mode(conv_ongoing) | confirmed | `neupsl.py:139` |
| ターゲット述語 Mode10 / Role6 / Rel6 クラス | confirmed | `neupsl.py:21-27` (MODES/ROLES/RELS) |
| Łukasiewicz: 連言 max(0,Σ-(k-1))・否定 1-v・含意違反 body-head | confirmed | `neupsl.py:214-225, 287-301` |
| 接地: 非持続=全フレーム / t_persist_mode=f∈[1,n)×10mode で前後連結 | confirmed | `neupsl.py:233-248` |
| エネルギー: 二乗ヒンジ(p=2, FLAGS.p2) w·viol² | confirmed | `neupsl.py:280-306` |
| エネルギー: クラス負事前 + εI Tikhonov (ε=0.005) (p_c+ε)y_c² | confirmed | `neupsl.py:307-316, _EPS_TIK 321` |
| MAP: 射影劣勾配 + 層ごと単体射影、eta=0.20/√(1+0.15t)、決定的早期収束 | confirmed | `neupsl.py:329-365`, `_project_simplex 251-262` |
| infer_scenario iters=200、argmax でラベル | confirmed | `neupsl.py:376-386` |
| ① 蒸留事前学習 BCE full-batch GD, steps=400, lr=0.5, 不均衡補正、θ 更新 | confirmed | `neupsl.py:409-442`, `_PRED_TARGET 393-406` |
| ② 構造化パーセプトロン: loss-augmented MAP(層別×クラス逆頻度マージン) | confirmed | `neupsl.py:445-459, 515-523` |
| ② w_psl=単体上の正規化指数勾配(総質量固定)+log バリア | confirmed | `neupsl.py:540-549` |
| ② θ=極小 lr_n=0.006、priors=小 SGD、平均化パーセプトロン | confirmed | `neupsl.py:482, 555-586, 587-602` |
| ③ bilevel BCE: Moreau 包絡・minimizer-based、w_psl と ŷ 更新 | confirmed | `neupsl.py:612-724`(prox 630-663, w/prior/mlp 665-710) |
| ③ N3 レシピは θ 凍結(`lr_n=0.0`)・基礎6→bilevel2 | confirmed | `run_supreme_situations.py:57-67, 386-404` |
| core が strict OFF で T2 を NeuPSL 結合 MAP 経路へ | confirmed | `core.py:1065-1068, 1273-1310` |
| learnable_param_count = rules29+priors22+mlp302 = neupsl353 (+t3 6 +scene 3 = 362) | confirmed | `neupsl.py:185-189`(埋め込み JSON params と一致) |

## 3. TBD / 未解決

- **TBD**: 個々のルールの**学習後**の最終重み。図は初期重みのみ(学習後は params 依存で決定的だが非図示)。
- **TBD**: MLP の学習後パラメータ値(決定的だが図には出さない)。
- レンダラ検証の唯一の警告は上記 2 件の unknowns 計上のみ(意味的警告なし)。

## 4. コードとドキュメントの食い違い(記録)

- `docs/NEUPSL_RULES.md` は supreme3 世代の記述で **全28本・Mode 9値/Role 6値/Rel 4値**のまま。
  現行コードは **29本・Mode 10/Role 6/Rel 6**(ADR 0053 が prior ルール3本を priors dict へ置換、
  ADR 0057 が新語彙ルール4本と述語3個を追加)。図・spec はコード側(29本, 10/6/6)を採用。
  当解説本体は埋め込み JSON で既に 29/10/6/6 を表示しており整合。NEUPSL_RULES.md の更新は本タスク対象外。
- `fit_bilevel` の既定は `lr_n=0.004`(θ を更新しうる)。**θ 凍結は関数既定ではなく N3 レシピの配線**
  (`_BILEVEL_KW: lr_n=0.0`)による。図(b)と本文はこの区別を明記(「N3 は lr_n=0」)。

## 5. skill 受入チェックリスト

### 意味的正しさ
- [x] ニューラル入力 x_nn と記号観測 x_sy を分離(観測述語は g_θ を迂回する矢印で明示)。
- [x] 全ニューラル出力が名前つき述語(12 ニューラル述語)にマップ(曖昧な「PSL 入力」にしない)。
- [x] observed / target / neural を形と枠で区別(平行四辺形/二重緑楕円状/二重青枠)。latent は無し(実装に無い)。
- [x] 代表ルールは実構文(`body → head ^2`・重み付き)。if 文の分岐として描かない。
- [x] 接地(全フレーム×3層・t_persist 連結)をエネルギー構築の前段に置く。
- [x] ハード制約は無し(全ソフト)。単体制約は MAP の feasibility として推論ノードに明記。
- [x] 結合 MAP の対象変数(Mode/Role/Rel 全フレーム)を明示。
- [x] 推論出力(y*)を生ニューラル出力と取り違えない(別ゾーン・argmax 後にラベル)。
- [x] 教師データ(GT)は図(b)のみ・truth-only の破線枠。推論の入力に出さない。
- [x] 凍結/学習対象を実装通り(①θ, ②w+prior+θ極小, ③w+ŷ・θ凍結(N3))。

### 視覚的正しさ
- [x] 読み順が明快(左→右6ゾーン、番号つきゾーンラベル)。
- [x] 交差矢印なし(スパインを上下段に振り、観測は下部迂回レールで分離)。
- [x] 全矢印種を凡例で定義(実線/破線/点線)。
- [x] 色のみに依存しない(枠形状 = 役割: 平行四辺形/太緑枠/二重青枠/二重緑枠/付箋/六角形)。
- [x] 最終紙面幅で可読(node text 14px、sub 13px、edge/mono 12.5px)。effective px ≈ nominal(viewBox≈表示幅)。
- [x] 提案の中核(g_θ)のみ強調(太緑枠)。他は静穏。
- [x] overview は主要ノード 11個(6-12 の範囲内)。詳細は述語/ルール表へ退避。
- [x] SVG はクリップ無し(全 11 SVG が XML well-formed、座標は箱内に収まる)。
- [x] グレースケール可読(形状 + 実線/破線/点線で区別、色非依存)。

### トレーサビリティ
- [x] 各主張に file:line 証拠(§2)。TBD は明示(§3)。
- [x] ラベルはプロジェクト語彙(ConvEv/Mode(emergency)/t_persist_mode 等、実名)。
- [x] 前提を本監査に列挙(§1)。
- [x] 図ソースは編集可能・版管理下(`neupsl-architecture-spec.yaml`)。

## 6. ページ整合性の検証結果 (機械実行)

- **HTMLParser タグ均衡**: OK(未閉じ open 0・エラー 0。void 2・self-close/SVG 58)。
- **埋め込み JSON == results.json**: 0 mismatch(rejection/N3/N3std/fit/meta.* を突合、埋め込みは未改変)。
- **mermaid セクション**: 未改変。nodes 21 / edges 31(21/31 整合)。
- **node --check**: inline JS 2ブロック(head テーマ初期化・本体 IIFE)ともに構文 OK。
- **SVG XML well-formed**: 図(a)(b)+凡例 9スウォッチ = 全 11 SVG が整形式。
- **コントラスト(図テキスト・実出現ペア)**: light/dark 両テーマで全て ≥4.5:1。
  最悪値 light 4.71(accent/zone)・dark 6.54。zone 背景は card2@opacity0.5 over card の実混色 `#f2f4f7`(light)で計算。
  `--good` テキストは card 上のみ(good/card 4.77/6.81)。非テキスト枠線も全て ≥3:1(最小 4.61)。
- **レンダラ検証**: `render_architecture.py` exit 0、警告は unknowns 2件のみ(意味的警告 0)。svg/pdf/png 生成 OK。
- **視覚ラスタ**: 本ヘッドレス環境に cairosvg/rsvg/inkscape/magick 無しのため PNG ラスタは未実施。
  代替として全ラベル幅を算定し、各箱内に収まること(最広 ~224px ≤ 箱幅 280px/最小箱 14文字 ≤ 140px)を確認。

## 7. 変更ファイル

- `docs/architecture-explainer.html` — ③節の `.tri` 3要素図を図(a)+図(b)+凡例へ差し替え、CSS 追加、
  導入文・レシピ導入文をゾーン/図(b)参照へ調整。他(①②④⑤⑥⑦節・各層解説・mermaid・埋め込み JSON・JS)は不変。
- `docs/neupsl-architecture-spec.yaml` — 新規(source of truth)。
- `docs/neupsl-architecture-audit.md` — 本ファイル(新規)。

## 8. 図解リデザイン(2026-07-23・出力カタログ + 配線図 + 実測トレース)

③節の図(a)6ゾーン概観を、承認済みリデザインへ差し替えた。図(b)学習図と mermaid・埋め込み JSON・
①②④⑤⑥⑦本文は不変。追加分もすべてページ内 JSON(機械生成)から描画する。

### 8.1 出力カタログ(A・新規)
- ③冒頭に 8 層(EPI)のカードグリッドを新設。各カードは 層名 + 日本語の役割 1 文(`layer_table.plain`)+
  全語彙チップ(`layer_table.vocab`)+ 語彙数バッジ + N3 pooled acc のミニバー(`N3.pooled.layers`)。
  クリックで ④ 該当層の `.lsec[data-layer]` へスムーズスクロール(④ の HTML は不変・JS が遷移を付与)。
- 語彙数(コードで検証): mode 10 / role 6 / rel 6 / t3 10 / risk 3 / t1 4 / quality 3 / scene 3。

### 8.2 NeuPSL 配線図(B・図(a)を置換)
- 5 列のインタラクティブ配線(inline SVG を JS がデータ駆動で生成)。列: ①観測原子14+派生特徴4 →
  ②ニューラル述語12(入力次元バッジ)→ ③ルール6群(mode10/role6/rel4/層間4/新語彙4/持続1)→
  ④ターゲット3ヘッド(Mode10/Role6/Rel6=22値/フレーム)→ ⑤結合MAP→出力。
- **トポロジは実コードから抽出**(`src/supreme/neupsl.py`)。ノード 41・ワイヤ 74。ワイヤ種別内訳:
  - `in`(観測原子/派生特徴 → 述語): **34** 本。`PREDICATES` の各特徴キー→述語 MLP 入力(`neupsl.py:63-76, 199-208`)。
  - `ag`(観測原子 → ルール群): **10** 本。ルール body 中の観測述語→所属群(`neupsl.py:133-169`)。
  - `pg`(ニューラル述語 → ルール群): **15** 本。ルール body 中のニューラル述語→所属群(同上)。
  - `gt`(ルール群 → ターゲットヘッド): **8** 本(mode→Mode, role→Role, rel→Rel, 層間→Role/Rel, 新語彙→Mode/Rel, 持続→Mode)。
  - `fb`(ターゲット → ルール群・帰還): **2** 本。層間整合 body の Mode 開述語(`x_*`)と持続 `PREV_MODE`(`neupsl.py:158-161, 168, 216-224`)。
  - `tm`(ヘッド → 結合MAP): **3** / `mo`(MAP → 出力): **1** / `t3`(Mode系列 → T3窓): **1**。
- **派生特徴 4(speaking/range_n/near3/h_q)**: MLP 入力キーのうち `OBSERVED` に無いもの。前処理(role/relation
  evidence・最小距離・quality h_q)由来で、`core._neupsl_features`(`core.py:1214-1241`)が算出。図では
  観測 14 と別の破線枠サブ群として表示(count callout は「観測14原子」を維持しつつ「＋派生4」を併記)。
- **未参照ノード(コードから判明した実際の findings・図で点線枠「未参照」表示)**:
  - `t1_pass`(観測述語・`OBSERVED` の 1 つ): どのルール body にも述語入力にも現れない(接続数 0)。
    `core._neupsl_features` は値を算出するが、現行 `RULES`/`PREDICATES` は参照しない。
  - `NearEv`(ニューラル述語): 上流(range_n/near3)はあるが、どのルール body も参照しない(下流 0)。
  - 検証規則「全ノード ≥1 ワイヤ」はこの 2 ノードを "unused" 明示として除外(捏造の配線は張らない)。
- **カウント callout**: 1 フレーム = 観測14原子(＋派生4)→ 述語12値 → ターゲット22値。eval 平均
  17.3 フレーム/シナリオ(4,057÷235)なので 1 シナリオ約 380 変数(22×17.3)を 1 回の結合 MAP で同時決定。
- **インタラクティブ**: ノードに hover / focus で上流+下流の推移閉包(BFS)を強調・非関連を opacity 0.15 へ
  200ms ease で減光。クリックでピン留め、Esc・余白クリックで解除(タッチはクリックで動作)。凡例で説明。
- **実測トレース重ね表示**: トグルで下記トレースの実値バッジをノードへ重畳(述語値・ターゲット argmax・
  ON 観測原子)。

### 8.3 実測トレース例(C・新規) — `reports/situations_v1-eval-20260722/dump_neupsl_trace.py`
- **再学習なし**: cache/all_t3scene.pkl(SupremeParams)+ cache/all_t2final.pkl(value["t2"]=NeuPSLParams)を
  直接 unpickle し `dataclasses.replace(t3scene, t2=...)` で params を復元(build_handwired_params と同一結果)。
- eval 1 シナリオを本番同一経路 `core.run_supreme_scenarios(..., STRICT_OFF)` で実走し、`neupsl.map_inference` を
  monkeypatch して vals_seq(述語真理値)と MAP 解 y を横取り。ルール寄与は `_rule_instances`/`_atom_value`/
  `FLAGS` を再利用して当該フレームの w·viol² を再計算(refit ではない)。
- **選択規則(決定的)**: suite=emg・eval 非違反を sid 昇順で走らせ、pred t2_mode==GT t2_mode=='emergency' の
  フレームをもつ最初のシナリオの最小 index フレーム。→ emg-alarm_while_degraded / crowd_panic / double_alarm は
  該当無しでスキップ、**emg-emergency_passing-eval-02 の frame 1(ts 0.5)**を採用。
- **INTEGRITY(script が停止条件つき assert)**: MAP argmax(mode/role/rel)== 実走 view == frames-N3.json の
  当該フレーム pred。一致を確認(mode=emergency, role=source_alarm, rel=unrelated)。
- **主な実値**: 観測 ON = siren/vehicle/risk_danger(=1.0)・objects_n(0.5)。述語 FarEv=0.856・DepEv=0.651・
  LowQ=0.505。分布 Mode(emergency)=0.680 / Role(source_alarm)=0.837 / Rel(unrelated)=0.522。GT は
  mode/role 一致・rel は approaching で相違(観測 approaching が立たず特徴不足)。寄与上位(学習後 w):
  r_siren_alarm(w0.645, viol0.163, 0.0172)> r_danger_emerg(w0.058, 0.0060)> r_far_unrel(0.0048)。
  重みは学習後値で初期値(r_danger_emerg 5.0 等)から大きく変化。
- **provenance**: sid=emg-emergency_passing-eval-02 / frame 1 / ts 0.5 / engine HEAD f70e3c9 /
  data HEAD 079e4309 / params は 5b544318 世代キャッシュ(src/supreme は両 HEAD 間で無変更・§4 参照)。
- 出力 `neupsl_trace-N3.json`(script 隣)。ページには要点を trimmed 埋め込み(`trace-data`)し、実値一致を検証。

### 8.4 検証結果(機械実行・全 PASS)
- HTMLParser タグ均衡: 未閉じ 0・stray 0。
- inline JS 2 ブロック `node --check`: 両方 OK(head テーマ初期化・本体 IIFE 31.8KB)。
- 埋め込み JSON: `ex-data` の N3 pooled == results.json(0 mismatch・ex-data 無改変)。`wiring-data`/`trace-data` パース OK。
- 配線図の静的検証: 41 ノード / 74 ワイヤ・dangling 0・orphan 0(unused 明示 t1_pass/NearEv を除く)。
  実データで JS を実走させ生成 SVG を XML パース(well-formed)・ノード 41/ワイヤ 74/カード 8 を確認。列内重なり 0。
- `trace-data` の値 == `neupsl_trace-N3.json`(0 mismatch)。argmax mode==emergency==view==GT。
- 静的 inline SVG: 14/14 well-formed。mermaid 節不変(nodes 21 / edges 31)。
- コントラスト(新規テキストペア・light/dark 両テーマ): 全て ≥4.5:1(最悪 4.58 light dtag.gt accent/card2)。
  map/out/dtag.am の塗り上テキストはテーマ別(light=白 / dark=#0f1419)、trace バッジ文字は `--ink`。

### 8.5 追加・変更ファイル
- `docs/architecture-explainer.html` — ③節の図(a)を出力カタログ + 配線図 + 実測トレースへ差し替え、CSS/JS/JSON
  2 ブロック追加、④ `.lsec` へ JS で id/scroll を付与(HTML 不変)、図(b)凡例を学習図専用に整理。図(b)本体は不変。
- `reports/situations_v1-eval-20260722/dump_neupsl_trace.py` + `neupsl_trace-N3.json` — 新規(トレース生成器と出力)。
- `docs/neupsl-architecture-spec.yaml` — `topology:` 節を追記(下記)。
