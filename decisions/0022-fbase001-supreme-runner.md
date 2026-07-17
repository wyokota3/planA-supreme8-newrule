# ADR 0022: F-基盤-001 — supreme 上流共有基盤(end-to-end ランナー)の機能定義

- 日付: 2026-06-14
- ステータス: 採用
- 関連: CLAUDE.md「共通基盤は F-基盤-XXX として切り出す」、SPEC `epiin`/`epiout`(stage)、ADR 0006(v1.4 語彙・入力契約・Delta非対応)、
  ADR 0010/0012/0017/0018/0019/0020/0021(各モジュール)、baseline `external-data/planA-baseline/src/ns_epi/{runner,gate,t2,quality,anomaly,hgf}.py`、runner 調査
- 決定者: ユーザー承認(2026-06-14・A 案=基盤を切り出す + 3スコープ決定は推奨採用)

## 背景

構築済みの supreme 8モジュール(T0/T1/role/mode/relation/quality/scene/T3)は**入力を注入される形**で個別検証されてきた。
F-013(封印評価)が封印セットで supreme を**実走**するには、**PSO入力 → 証拠抽出 → 各モジュール → 8層 view** を組み立てる
**上流共有基盤**が必要。SPEC の機能リストに無いため、新機能 **F-基盤-001** として切り出す(`epiin`/`epiout` stage の空白を埋める)。
baseline runner のフロー(quality→anomaly→t0→t1→t2→scene→t3)・依存・状態持ち越しは調査で完全に判明。

## 決定(スコープ)

### 目的 = `run_supreme(PSO入力系列) → trace`
各フレームの **8層 view**(risk_tier/t1_state/t2_mode/t2_role/t2_relation/t3_hypothesis/quality_regime/scene_regime)を
生成し、harness.score / search の scorer / F-013 封印評価が消費できる trace を返す。

### 決定1: 出力は8層 view に絞る
契約フル emit(EPI-T0..T3/CTRL/NOVEL レコード・relevance/next_beat・契約フル検証)は **F-013 の採点に不要**なので
**別課題に申し送り**。F-基盤-001 は 8層 view trace(+ gt 突合に必要な最小)に集中。

### 決定2: T3 reset 発火源 = シナリオ境界
計測で baseline のエピソード境界=シナリオ境界(各シナリオ=1エピソード)と判明。**シナリオ先頭フレームで reset=True**
を T3 へ注入(ADR 0018: リセット源=注入・発火源は上流=本基盤がシナリオ境界で供給)。

### 決定3: quality h_q/vol(と anomaly pw_anom)は baseline 観測式 + 共有 HGF で再実装
supreme quality.classify は (h_q,vol) を受けるだけ(観測式/HGF 無し)。本基盤が **baseline 観測式**
(`logit = -2 + 5·qos - 4·(latency/200) - 2.5·(1-id_const) + 1.5·w_obs_bar` → sigmoid → HGF)で h_q/vol を生成。
**HGF カーネルは F-010(scene)で独立実装済みを共有基盤として再利用**。anomaly の precision_weight も同様に HGF で生成し T1 へ。

### 確定事項(既存 ADR)
- **Snapshot のみ受理**・Delta/fields_ref は明示エラー(ADR 0006 決定3)。任意フィールド欠落は縮退。ts 単調非減少検証。
- **単一スレッド**(thread=None)・ctrl 命令プレーン/NOVEL/multi-thread 合議は除外(8層採点に不要)。
- **baseline 忠実な独立再実装**(baseline/ns_epi/external を import・参照しない・F-006-2 流儀)。決定的(F-004-2)。
- 語彙マッピング: baseline 流の logit キー ↔ supreme v1.4 統制語彙(mode 2クラスリネーム・quality 順位シフト・ADR 0006)。

## 構成要素(新規実装 / 既存再利用)

**新規実装(F-基盤-001 スコープ)**:
1. gate(PSO Snapshot → world_state・検証)
2. 証拠抽出(world_state → 各モジュール入力: quality 入力・anomaly 特徴・t2 evidence・t0/t1 入力)
3. 観測式 + HGF 前処理(quality h_q/vol・anomaly pw_anom。HGF は F-010 を共有)
4. 段2 mode logits 生成(evidence → mode logits・mode.hysteresis へ)
5. 結線/状態管理(tick オーケストレーション・prev_* 持ち越し・T3 シナリオ境界 reset)
6. 8層 view 組み立て(argmax 含む)+ trace
7. 語彙マッピング(v1.4)

**既存 supreme モジュール再利用(改変不可)**:
t0.risk_tier / t1.t1_state / role.classify / relation.classify / mode.hysteresis / quality.classify /
scene(hgf_filter/classify) / t3(run_t3_sequence/step) / harness / search。

## 受け入れ条件(新規定義)

- **F-基盤-001-1**: PSO Snapshot 入力系列から end-to-end で **8層 view trace** を生成する(全モジュールを baseline 依存フローで
  正しく結線・tick 間状態持ち越し・T3 はシナリオ境界 reset)。trace は harness.score に渡せる形。
- **F-基盤-001-2**: **決定的**(同一入力で trace 完全再現・F-004-2 合格・乱数/時刻なし)。**独立性**(baseline/ns_epi/external を
  実行時・静的にリンクしない・F-006-2 流儀)。
- **F-基盤-001-3**: **Snapshot のみ受理**・Delta/fields_ref は明示エラー・任意フィールド欠落は縮退・ts 単調非減少検証。
- **F-基盤-001-4**: 8層 view は **v1.4 統制語彙**(baseline logit からの語彙マッピング適用)。各層が v1.4 語彙に閉じる。

## 影響

- F-基盤-001 完成で supreme が **end-to-end 実走可能**に。F-012 の scorer・F-013 の封印評価が実走可能になる。
- アーキ: `epiin`(入力契約)・`epiout`(出力契約=8層 view)の stage が F-基盤-001 で実装される。新ノード `core`(統合ランナー)を追加。
- 受け入れ条件は**組み立て正しさ + 規律**(決定性・独立性・Snapshot規律・v1.4語彙)。実際の精度・改善は F-013 で測定(成功目標)。

## 追記: 観測式→HGF の解釈と暗黙仕様(2026-06-14・監査 `reports/audit-20260614-1150-Fbase001.md`)

- **観測式→HGF の正確な解釈(コード修正不要・字面の是正)**: 上の決定3 は「観測式 → sigmoid → HGF → h_q=sigmoid(μ1)」と読めるが、これは**二重 sigmoid**になり高 QoS でも h_q≈0.72 止まりで GOOD ゲート(h_q≥0.93)に届かない。実装は**生 logit を HGF 入力にし h_q=sigmoid(μ1)** を採用(高QoS→GOOD・低QoS→BLOCK が成立)。監査は「単調性により方向性が構造的に頑健=過適合でない」と評価。**正は「生 logit → HGF → h_q=sigmoid(μ1)」**(scene へは別途 sigmoid 済み health 信号 [0,1] を渡す=空間が異なる点を保守時に保つこと)。
- **非安全 mode 同士の tie 優先順位は暗黙仕様**: 現状 dict 挿入順で決定的(再現性は担保)だが ADR/テストで明文化していない。将来 mode logit の同値競合を固定したい場合は ADR 追記+テストが先(低優先・F-013 着手には影響しない)。
- **wiring 用チューニング定数**(観測式係数・mode logit 係数・scene 閾値)は方向性(siren→caution・低QoS→BLOCK 等)を満たす出発値。F-013 の δ_strong 測定時に core.py 先頭付近の係数を起点に調整する。

## 残件・申し送り

- **契約フル emit**(EPI-T0..T3/CTRL/NOVEL・relevance/next_beat・契約フル検証)は別課題(F-013 採点に不要・ADR 0006 決定4 の完全充足は将来)。
- **baseline 再計測**(v1.4・210規約)は研究者手動(F-013 まで)。
- observation 式/HGF パラメータ・証拠抽出の閾値は baseline 忠実値を出発点(δ_strong は F-013 測定)。
- reset 発火源を将来 scene cut 連動にするなら別途(現状=シナリオ境界)。
- F-013 の着手条件(SearchGate×SealStore 経路合成・ADR 0010)は F-013 で解く。
