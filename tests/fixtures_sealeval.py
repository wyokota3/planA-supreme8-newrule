"""F-013 封印評価用フィクスチャ（決定的・stdlib のみ・実装コードではない）。

方針（指示・ADR 0023・TEST_STRATEGY「テストデータ管理」/「穴2」）:
- 依存は stdlib + pytest のみ。ダミー封印 GT・ダミー baseline スコア・PSO 入力を
  dict リテラルで決定的に合成する。乱数・時刻なし（ts は呼び出し側＝テストが供給）。
- **本番封印は開けない**。常用テストは production=False のダミー封印で経路をドライランする。
- ダミー封印 GT には親系統タグ（GT_SCHEMA: meta.parent_lineage_id / parents / generation）を
  持たせ、リーク検査 fixture が跨がないこと（封印 root は train root と非交差な独立 root）。
- 封印レコードは GT のみ保持し PSO 入力を持たない（ADR 0023 決定2 の seam）。よって
  「封印 GT（scenario_id で対応）」と「PSO 入力（scenario_id で対応）」を**別系統**で用意する。
- 既存 fixtures_gt / fixtures_pso / fixtures_harness を最大限再利用する。

ここで定義する sealeval が前提とする supreme.sealeval / SealStore の契約は
各 test_F013_*.py の docstring が定義する（implementer はテストを変えない）。
"""

import copy

import fixtures_gt as fxg
import fixtures_pso as fxp


# F-013 採点の 8層（ADR 0012 / canonical_metric_spec）。
EIGHT_LAYERS = (
    "risk_tier", "t1_state", "t2_mode", "t2_role", "t2_relation",
    "t3_hypothesis", "quality_regime", "scene_regime",
)

# 評価項目 ↔ 8層 の対応（GT_SCHEMA「9評価項目との対応」・Anomaly は採点外）。
# 弱い5項目（mode/relation/T3/Scene/Quality）と強い3項目（T0/T1/role）。
WEAK_ITEMS = ("t2_mode", "t2_relation", "t3_hypothesis", "scene_regime", "quality_regime")
STRONG_ITEMS = ("risk_tier", "t1_state", "t2_role")

# δ_strong（U5b・暫定 0.02）。テストが compare_items / run_sealed_evaluation に明示供給する。
DELTA_STRONG = 0.02


# ---------------------------------------------------------------------------
# ダミー封印 GT レコード（親系統タグ付き・封印適格 human root・独立 root）
#
#   封印 root: SEAL_P / SEAL_Q  （いずれも gt_origin="human"・generation=0・自身が root）
#   練習 root: TRAIN_R          （train 側・封印と非交差なことを示す素材）
#
# 封印 GT は GT_SCHEMA canonical 形（meta/gt/custom）。フレームの t2 分布は argmax を
# 固定し、t3 文字列は完全一致採点に乗る値にする（fixtures_gt.canonical_records_for_trace の流儀）。
# ---------------------------------------------------------------------------

def _sealed_record(scenario_id, *, parent_lineage_id=None, frames_spec):
    """封印適格な canonical GT レコードを作る（human root・親系統タグ付き）。

    frames_spec: [(ts, {layer_label: value, ...}), ...]
      8層のうち固定したいラベルだけ与える（残りは fixtures_gt._frame の既定）。
      t2_mode/t2_relation/t2_role は確率分布 argmax を指定ラベルに寄せる。
      risk_tier(t0)/t1_state(t1)/t3_hypothesis/quality_regime/scene_regime は文字列。
    """
    rec = fxg.make_record(
        scenario_id,
        parent_lineage_id=parent_lineage_id,
        gt_origin="human",
        n_frames=len(frames_spec),
    )
    # custom に親系統タグの注記（GT_SCHEMA: custom はパススルー）。リーク検査素材の明示。
    rec["custom"] = {"seal_family_tag": parent_lineage_id or scenario_id}

    frames = []
    for ts, labels in frames_spec:
        fr = fxg._frame(ts)
        # t2 分布 argmax を寄せる
        for layer_key, dist_keys in (
            ("t2_mode", fxg.T2_MODE_KEYS),
            ("t2_relation", fxg.T2_RELATIONS_KEYS),
            ("t2_role", fxg.T2_ROLES_KEYS),
        ):
            label = labels.get(layer_key)
            if label is not None:
                d = {k: 0.0 for k in dist_keys}
                d[label] = 1.0
                # t2 内のキー名は mode/relations/roles
                inner = {"t2_mode": "mode", "t2_relation": "relations",
                         "t2_role": "roles"}[layer_key]
                fr["t2"][inner] = d
        # t0 / t1 / t3 文字列
        if "risk_tier" in labels:
            fr["t0"]["risk_tier"] = labels["risk_tier"]
        if "t1_state" in labels:
            fr["t1"]["state"] = labels["t1_state"]
        if "t3_hypothesis" in labels:
            fr["t3"]["hypothesis"] = labels["t3_hypothesis"]
        if "quality_regime" in labels:
            fr["t3"]["quality_regime"] = labels["quality_regime"]
        if "scene_regime" in labels:
            fr["t3"]["scene_regime"] = labels["scene_regime"]
        frames.append(fr)

    rec["gt"]["frames"] = frames
    return rec


def sealed_records_two_scenarios():
    """封印 2 シナリオ（SEAL_P / SEAL_Q）の canonical GT レコード群。

    親系統: SEAL_P / SEAL_Q はそれぞれ独立 root（human・generation=0）。
    train 系統 TRAIN_R とは交差しない（リーク検査 fixture が跨がない素材）。

    GT ラベルは全フレーム共通の「正解」を固定（採点の手計算が効くよう単純化）:
      risk_tier=tier0 / t1_state=idle / t2_mode=conv_request / t2_role=source_speech /
      t2_relation=addressing_user / t3_hypothesis=indoor_quiet /
      quality_regime=GOOD / scene_regime=STABLE
    """
    labels = {
        "risk_tier": "tier0",
        "t1_state": "idle",
        "t2_mode": "conv_request",
        "t2_role": "source_speech",
        "t2_relation": "addressing_user",
        "t3_hypothesis": "indoor_quiet",
        "quality_regime": "GOOD",
        "scene_regime": "STABLE",
    }
    p = _sealed_record("SEAL_P", parent_lineage_id="SEAL_P",
                       frames_spec=[(0.0, labels), (1.0, labels)])
    q = _sealed_record("SEAL_Q", parent_lineage_id="SEAL_Q",
                       frames_spec=[(0.0, labels), (1.0, labels)])
    return [p, q]


def sealed_record_all_null_scene():
    """scene_regime（弱い項目）の GT が全フレーム no_data になる封印レコード。

    ADR 0023 決定4: 封印に当該層データが無い項目は no_data として勝敗から除外。
    scene_regime の gt を全フレーム None にし、「全null層 → no_data」を引き出す素材。
    他層は通常の正解ラベル。
    """
    labels = {
        "risk_tier": "tier0", "t1_state": "idle", "t2_mode": "conv_request",
        "t2_role": "source_speech", "t2_relation": "addressing_user",
        "t3_hypothesis": "indoor_quiet", "quality_regime": "GOOD",
        "scene_regime": "STABLE",
    }
    rec = _sealed_record("SEAL_NULLSCENE", parent_lineage_id="SEAL_NULLSCENE",
                         frames_spec=[(0.0, labels), (1.0, labels)])
    # scene_regime を全フレーム null（no_data 素材）にする。
    for fr in rec["gt"]["frames"]:
        fr["t3"]["scene_regime"] = None
    return rec


def train_root_record():
    """練習用（train）side の独立 root（封印と非交差を示すリーク検査素材）。"""
    r = fxg.make_record("TRAIN_R", gt_origin="ai_generated")
    return fxg.with_split(r, "train")


# ---------------------------------------------------------------------------
# PSO 入力（scenario_id で封印 GT と対応づける別系統・ADR 0023 決定2 の seam）
#
# 封印 GT は PSO を持たないので、scenario_id をキーにした PSO-Snapshot 系列を別に用意する。
# 形状は fixtures_pso（PSO-Snapshot/1.4）。フレーム数は対応する封印 GT と揃える。
# ---------------------------------------------------------------------------

def pso_snapshots_for(scenario_id, n_frames=2):
    """scenario_id に対応する決定的 PSO-Snapshot 系列（会話証拠・n_frames）。"""
    return [fxp.frame_conversation(ts=float(i), r_m=2.0, speaking_prob=0.95)
            for i in range(n_frames)]


def pso_inputs_two_scenarios():
    """封印 SEAL_P / SEAL_Q に対応する PSO 入力（scenario_id -> snapshots）。"""
    return {
        "SEAL_P": pso_snapshots_for("SEAL_P", n_frames=2),
        "SEAL_Q": pso_snapshots_for("SEAL_Q", n_frames=2),
    }


def seal_scenario_inputs_two():
    """seal_scenario_to_pso 用の封印シナリオ入力（決定的・scenario_id 付き）。

    アダプタが「封印シナリオ入力 → pso_snapshots」へ変換する境界の入力素材。
    形状は実装裁量（ADR 0023 で seam の境界のみ規定）なので、テストは
    「同一入力 → 同一 pso_snapshots（決定的）」と「scenario_id ごとに分離」を固定する。
    """
    return {
        "SEAL_P": {"scenario_id": "SEAL_P", "frames": [{"ts": 0.0}, {"ts": 1.0}]},
        "SEAL_Q": {"scenario_id": "SEAL_Q", "frames": [{"ts": 0.0}, {"ts": 1.0}]},
    }


# ---------------------------------------------------------------------------
# ダミー baseline スコア（研究者手動取り込みの素材・canonical layer schema 準拠）
#
# baseline は実行しない（取り込むだけ）。8層 acc の dict を与える。
# canonical_metric_spec の layer schema と一致しない入力は load_baseline_scores が停止する。
# ---------------------------------------------------------------------------

def baseline_scores_canonical():
    """canonical 8層に一致する正常な baseline スコア（取り込み正常系）。

    層 acc を手で与える（[0,1]）。verdict の境界テストはこの値を上書きして使う。
    """
    return {layer: 0.50 for layer in EIGHT_LAYERS}


def baseline_scores_missing_layer():
    """canonical layer schema 不一致（scene_regime 欠落）の baseline スコア。

    load_baseline_scores が「黙って採点しない＝停止」することの素材（ADR 0023 決定3）。
    """
    d = baseline_scores_canonical()
    del d["scene_regime"]
    return d


def baseline_scores_extra_layer():
    """canonical layer schema 不一致（未知層 Anomaly 混入）の baseline スコア。

    Anomaly は採点外（ADR 0012 決定C）。layer schema に無い層が混じる入力も停止対象。
    """
    d = baseline_scores_canonical()
    d["Anomaly"] = 0.9
    return d


def baseline_scores_with(values):
    """canonical 8層を基準に、指定層だけ上書きした baseline スコアを返す（境界構成用）。"""
    d = baseline_scores_canonical()
    d.update(values)
    return d
