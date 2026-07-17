# GT 単一スキーマ（F-001-2 の契約）

> 導出元: `https://github.com/wyokota3/N04-scenario-contract.git` の **feat/ns016-020-role-relation-gt ブランチ**
> @ `a0b882215e4bd4320b878853fa23b30a0661baab`(**catalog 1.4.0** = baseline 測定GTと完全一致)の
> `scenarios/v021_core/` 全20シナリオ・210フレームの `ground_truth.yaml`(構造は20件で一貫)。
> ローカル: `C:\work\L04-planA\supreme\external-data\n04-feat`(worktree・本リポジトリ外)。
> 確定の経緯: ADR 0003(初版・main@de77b04 由来)→ ADR 0005(正準GTを feat 1.4.0 に改ピン)→
> **ADR 0006(2026-06-12 契約 v1.4 系へ移行)**: 本スキーマの語彙は **v1.4 統制語彙**。
> feat の生GT(v1.3 語彙)は**取込前に契約定義の機械マッピングを適用**する
> (mode: alert_observation→side_rear_caution, conv_participation→uncertain ／
> quality: PASS→DEGRADED, DEGRADED→BLOCK の順位シフト)。

## canonical GT record(正規形)

datagov が管理する1データ＝1レコード。3層構造。

```yaml
meta:                      # datagov が付与する管理層
  scenario_id: str         # 一意。例 "ns-epi-v021-ns001-boot-sanity"
  source:
    repo: str              # 取得元リポジトリ URL(ローカル生成なら "local")
    commit: str            # 取得元コミット(ローカル生成なら登録時の版識別子)
    path: str              # 例 "scenarios/v021_core/ns001_boot_sanity"
  parent_lineage_id: str   # root(親系統)の scenario_id。元シナリオは自分自身
  parents: [str]           # 直接親の scenario_id 列。root は []
  generation: int          # root=0、子=1、孫=2…
  split: str               # "train" | "seal" | "unassigned"
  gt_origin: str           # "ai_generated" | "human" | "cross_checked"
  registered_at: str       # ISO8601

gt:                        # 実データ由来の本体層(ground_truth.yaml の正規化)
  scenario_id: str         # meta.scenario_id と一致必須
  version: str
  description: str         # 任意(欠落は警告のみ)
  frames:                  # timeline に対応。ts 昇順
    - ts: float            # フレーム時刻(秒)。系列内で狭義単調増加
      t0:
        risk_tier: str|null
        kind: str|null
        range_m: float|null
      t1:
        state: str
        ttc_s: float
        min_range_m: float
      t2:                  # 6つの確率分布(クラス名→[0,1] の float)
        mode:      {conv_request, conv_ongoing, surround_activity, forward_caution,
                    side_rear_caution, alert_required, emergency, quiet_standby,
                    env_change, uncertain}   # v1.4 統制語彙(ADR 0006)
        relations: {addressing_user, near_user, approaching, grouped, departing, unrelated}
        roles:     {source_speech, source_vehicle, source_alarm, unknown,
                    source_human, source_object}
        hazard:    {safe, caution, danger}
        dynamics:  {approach, pass, depart, stop, idle}
        episode:   {ongoing, ending, regime_change}
      t3:
        scene_label: str
        outdoor_prob: float      # [0,1]
        vehicle_present: bool
        stability: float         # [0,1]
        next_beat: {state: str, p: float}   # p は [0,1]
        hypothesis: str
        quality_regime: str      # v1.4 統制語彙: GOOD / DEGRADED / BLOCK(feat 生GTは v1.3 語彙 GOOD/PASS/DEGRADED → 取込時マッピング)
        scene_regime: str        # v1.4 統制語彙: STABLE / CHANGING / DEGRADING

custom: {}                 # 不透明パススルー。バリデーション・突合の対象外
```

## バリデーション規則

| 区分 | 規則 |
| --- | --- |
| **拒否**(登録不可) | 必須キーの欠落・型不一致 ／ 文字列必須フィールドの**空文字列**(非空要求) ／ `meta.scenario_id` ≠ `gt.scenario_id` ／ **scenario_id の再登録**(リネージ不変性の担保) ／ **親系統不明**(`parents` の参照先が未登録、かつ root 宣言でもない) ／ **root 宣言の不整合**(`parents`=[] なのに `parent_lineage_id`≠自身 または `generation`≠0) ／ **`parent_lineage_id`・`generation` の検算不一致**(`parents` 連鎖から解決した値と不一致) ／ 確率値が [0,1] 外 ／ `ts` が単調増加でない ／ t2 各分布のクラスキー集合が上記定義と不一致(突合可能性が壊れるため) |
| **警告**(登録可・記録) | 分布の合計が 1±0.01 を外れる(封印GT・人手GTを過剰拘束しない) ／ `description` 欠落 |
| **検査しない** | `custom` 配下すべて |

- 文字列フィールド(`risk_tier`/`state`/`hypothesis`/`*_regime` 等)の**値集合は現時点で閉じない**が、
  **非空は拒否表で強制**する(空文字列は拒否。2026-06-12 監査反映)。契約 v1.4 の中身精査(U7)後に値集合の厳格化を検討する。

## 突合(F-001-2)

- 突合キー: `(scenario_id, ts)`。
- baseline 結果GT(F-005)・封印GT(F-002)も**本 canonical 形に正規化してから**突合する。
- F-001 時点の検証は**合成フィクスチャ**(ダミー封印GT・ダミー baseline 結果GT)で行い、
  F-002/F-005 実装時に実GTで再検証する(2段階方式・ADR 0003)。

## 9評価項目との対応

| 評価項目 | GTフィールド | 備考 |
| --- | --- | --- |
| mode(弱) | `frames[].t2.mode` | 確率分布 |
| relation(弱) | `frames[].t2.relations` | 確率分布 |
| T3(弱) | `frames[].t3.hypothesis` | 系列文脈・リセットは F-009/U4 |
| Scene regime(弱) | `frames[].t3.scene_regime` | |
| Quality regime(弱) | `frames[].t3.quality_regime` | |
| T0(強) | `frames[].t0.risk_tier` | kind/range_m は補助 |
| T1(強) | `frames[].t1.state` | ttc_s/min_range_m は補助 |
| role(強) | `frames[].t2.roles` | 確率分布 |
| Anomaly(強) | **GT に直接フィールド無し** | U10(指標定義)確定時に対応付けを定義。それまで Anomaly の採点はブロック |

## リネージ規則(F-001-1 / F-001-3)

- 元シナリオ(人手作成を含む): `parent_lineage_id`=自身、`parents`=[]、`generation`=0。
  **root 宣言はこの3条件をすべて満たすこと**(いずれか欠けは拒否。2026-06-12 監査反映)。
- 派生: `parents` に直接親を記録。`parent_lineage_id` は親の `parent_lineage_id` を**継承**(孫・ひ孫も推移的に root へ畳まれる)。
  非 root の `parent_lineage_id`・`generation` は `parents` 連鎖からの解決値と**検算一致**しなければ拒否(下流が `meta` を直接信頼してもリークしないため)。
- **複数親(マージ系統)は現仕様では不許容**(`LineageError`)。F-003 の増強で必要になれば本スキーマを改版し ADR で記録する。
- 任意データ → root の解決は推移閉包で一意(F-001-3)。
- 分割非交差: `split=seal` の親系統集合 ∩ `split=train` の親系統集合 = ∅ を払い出し時に assert(F-001-1)。

## 分割割当(自動・決定的)

- インターフェース: `assign_split(params)`。`params` = 封印側の件数または比率 ＋ 適格フィルタ
  (例: `gt_origin == "human"` のみ封印適格。フィルタの既定は F-002 で確定)。
- アルゴリズム: 適格な root 親系統IDを **sha256 ハッシュで安定ソート**し、先頭から封印に割当。
  乱数・時刻に依存せず、同一入力＋同一パラメータ → 同一割当(決定的)。
- 割当は版として記録し、再割当しても履歴を消さない。
- **分割の事後変更APIは置かない**(`set_split` は 2026-06-12 監査で削除)。正規の割当経路は `assign_split` のみ。
  `register` は `meta.split` をそのまま受理する(既定 `unassigned`。取込・状態復元・テストでの違反状態構成用)。
  `payout` は割当の経路に関わらず非交差を**防御的に**検証する。
