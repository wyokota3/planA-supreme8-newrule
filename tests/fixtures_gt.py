"""F-001 テスト用フィクスチャ（Python dict リテラル）。

方針（TEST_STRATEGY「テストデータ管理」/ 指示）:
- 依存は stdlib + pytest のみ。PyYAML 等の新規依存を増やさない。GT は dict リテラルで書く。
- 全テストデータに親系統タグ（meta.parent_lineage_id / parents / generation）を持たせる。
- 練習（train）/封印（seal）の区別を fixture 自身が持つ。
- スキーマは specs/GT_SCHEMA.md の canonical GT record（meta / gt / custom の3層）に厳密に従う。

ここに置く dict は「正規形（canonical）として妥当な GT レコード」を基準とし、
異常系テストは各テストでこの正規形を copy.deepcopy して1箇所だけ壊す方式を取る。
"""

import copy


# --- t2 の6分布のクラスキー集合（GT_SCHEMA.md の定義どおり。突合可能性の契約） ---

T2_MODE_KEYS = (
    "conv_request", "conv_ongoing", "surround_activity", "forward_caution",
    "side_rear_caution", "alert_required", "emergency", "quiet_standby",
    "env_change", "uncertain",
)
T2_RELATIONS_KEYS = (
    "addressing_user", "near_user", "approaching", "grouped", "departing", "unrelated",
)
T2_ROLES_KEYS = (
    "source_speech", "source_vehicle", "source_alarm", "unknown",
    "source_human", "source_object",
)
T2_HAZARD_KEYS = ("safe", "caution", "danger")
T2_DYNAMICS_KEYS = ("approach", "pass", "depart", "stop", "idle")
T2_EPISODE_KEYS = ("ongoing", "ending", "regime_change")


def _uniform(keys):
    """合計 1.0 ちょうどになる一様分布を作る（警告境界テストの基準）。"""
    n = len(keys)
    base = round(1.0 / n, 6)
    d = {k: base for k in keys}
    # 端数を最初のキーに寄せて合計を 1.0 に厳密化
    drift = round(1.0 - sum(d.values()), 6)
    first = keys[0]
    d[first] = round(d[first] + drift, 6)
    return d


def _frame(ts):
    """正規形として妥当な1フレームを作る。"""
    return {
        "ts": float(ts),
        "t0": {"risk_tier": "tier0", "kind": "none", "range_m": 12.5},
        "t1": {"state": "nominal", "ttc_s": 9.9, "min_range_m": 4.0},
        "t2": {
            "mode": _uniform(T2_MODE_KEYS),
            "relations": _uniform(T2_RELATIONS_KEYS),
            "roles": _uniform(T2_ROLES_KEYS),
            "hazard": _uniform(T2_HAZARD_KEYS),
            "dynamics": _uniform(T2_DYNAMICS_KEYS),
            "episode": _uniform(T2_EPISODE_KEYS),
        },
        "t3": {
            "scene_label": "lobby",
            "outdoor_prob": 0.1,
            "vehicle_present": False,
            "stability": 0.8,
            "next_beat": {"state": "hold", "p": 0.7},
            "hypothesis": "indoor_quiet",
            "quality_regime": "GOOD",
            "scene_regime": "STABLE",
        },
    }


def make_record(
    scenario_id,
    *,
    parent_lineage_id=None,
    parents=None,
    generation=0,
    split="unassigned",
    gt_origin="ai_generated",
    n_frames=2,
    ts_start=0.0,
    ts_step=1.0,
    description="synthetic fixture record",
    repo="local",
    commit="fixture-v1",
    path=None,
):
    """canonical GT record（meta / gt / custom の3層）を1件作る。

    parent_lineage_id 未指定なら root（自身が root）として scenario_id を入れる。
    """
    if parent_lineage_id is None:
        parent_lineage_id = scenario_id  # root: 自身が root（GT_SCHEMA.md）
    if parents is None:
        parents = []  # root は []
    if path is None:
        path = "scenarios/v021_core/" + scenario_id

    frames = [
        _frame(round(ts_start + i * ts_step, 6)) for i in range(n_frames)
    ]

    meta = {
        "scenario_id": scenario_id,
        "source": {"repo": repo, "commit": commit, "path": path},
        "parent_lineage_id": parent_lineage_id,
        "parents": list(parents),
        "generation": generation,
        "split": split,
        "gt_origin": gt_origin,
        "registered_at": "2026-06-12T00:00:00Z",
    }
    gt = {
        "scenario_id": scenario_id,
        "version": "1.0",
        "frames": frames,
    }
    if description is not None:
        gt["description"] = description

    return {"meta": meta, "gt": gt, "custom": {}}


def clone(record):
    """テスト内で1箇所だけ壊すための深いコピー。"""
    return copy.deepcopy(record)


def with_split(record, split):
    """レコードのコピーを返し meta.split を上書きする。

    2026-06-12 監査対処: set_split 削除後、違反状態・split 状態は
    「meta.split をレコードに直接指定して register する」データ駆動方式で構成する
    （改版 GT_SCHEMA「register は meta.split をそのまま受理（既定 unassigned）」）。
    """
    r = copy.deepcopy(record)
    r["meta"]["split"] = split
    return r


# ---------------------------------------------------------------------------
# 系統構成のフィクスチャ（リネージ／非交差／孫経由リークの素材）
#
#   A (root, gen0) ── A_c1 (gen1) ── A_gc1 (gen2)   ← この枝
#               └── A_c2 (gen1)                       ← A の別の子
#   B (root, gen0) ── B_c1 (gen1)
#   C (root, gen0)   ← human 由来・封印適格の素材
#   D (root, gen0)   ← human 由来・封印適格の素材
# ---------------------------------------------------------------------------

def lineage_family_A():
    """root A とその子孫。孫経由リークの素材（A の子孫は同一 root へ畳まれる）。"""
    A = make_record("A", generation=0, gt_origin="human")
    A_c1 = make_record(
        "A_c1", parent_lineage_id="A", parents=["A"], generation=1,
        gt_origin="ai_generated",
    )
    A_gc1 = make_record(
        "A_gc1", parent_lineage_id="A", parents=["A_c1"], generation=2,
        gt_origin="ai_generated",
    )
    A_c2 = make_record(
        "A_c2", parent_lineage_id="A", parents=["A"], generation=1,
        gt_origin="ai_generated",
    )
    return {"A": A, "A_c1": A_c1, "A_gc1": A_gc1, "A_c2": A_c2}


def lineage_family_B():
    B = make_record("B", generation=0, gt_origin="human")
    B_c1 = make_record(
        "B_c1", parent_lineage_id="B", parents=["B"], generation=1,
        gt_origin="ai_generated",
    )
    return {"B": B, "B_c1": B_c1}


def human_roots():
    """封印適格（gt_origin == "human"）な独立 root 群。"""
    return {
        "C": make_record("C", generation=0, gt_origin="human"),
        "D": make_record("D", generation=0, gt_origin="human"),
        "E": make_record("E", generation=0, gt_origin="human"),
        "F": make_record("F", generation=0, gt_origin="human"),
    }


# ---------------------------------------------------------------------------
# F-005 trace フィクスチャ（baseline 結果 trace.json と同形）
#
# trace 形式:
#   { "<scenario名>": [ { "ts": float, "view": {8層のラベル}, "gt": {8層のラベル} }, ... ], ... }
# 8層キー: risk_tier / t1_state / t2_mode / t2_role / t2_relation /
#           t3_hypothesis / quality_regime / scene_regime
#
# 弱い5項目(分析必須対象):
#   t2_mode, t2_relation, t3_hypothesis, quality_regime, scene_regime
# ---------------------------------------------------------------------------

# 8層の既知ラベル値（実データで使われる代表的な値）
_TRACE_DEFAULTS = {
    "risk_tier":     "tier0",
    "t1_state":      "nominal",
    "t2_mode":       "conv_request",
    "t2_role":       "source_speech",
    "t2_relation":   "addressing_user",
    "t3_hypothesis": "indoor_quiet",
    "quality_regime": "GOOD",
    "scene_regime":  "STABLE",
}


def make_trace_frame(ts, *, view_overrides=None, gt_overrides=None):
    """trace の1フレームを作る。

    view_overrides / gt_overrides で view/gt の任意の層を上書きできる。
    """
    view = copy.copy(_TRACE_DEFAULTS)
    gt_labels = copy.copy(_TRACE_DEFAULTS)
    if view_overrides:
        view.update(view_overrides)
    if gt_overrides:
        gt_labels.update(gt_overrides)
    return {"ts": float(ts), "view": view, "gt": gt_labels}


def make_trace(scenarios):
    """trace dict を作る。

    scenarios: {"<scenario_id>": [frame_dict, ...], ...}
    各 frame_dict は make_trace_frame() の戻り値。
    """
    return copy.deepcopy(scenarios)


def trace_perfect_2scenario():
    """2シナリオ×3フレーム、全フレーム正解（view == gt）の trace フィクスチャ。"""
    return {
        "sc1": [
            make_trace_frame(0.0),
            make_trace_frame(1.0),
            make_trace_frame(2.0),
        ],
        "sc2": [
            make_trace_frame(0.0),
            make_trace_frame(1.0),
            make_trace_frame(2.0),
        ],
    }


def trace_with_known_errors():
    """2シナリオ×3フレームで弱い5項目に既知の誤りを仕込んだ trace フィクスチャ。

    sc1: フレーム 1.0 で t2_mode のみ誤り(view=conv_ongoing, gt=conv_request)
    sc2: フレーム 0.0 で t2_relation 誤り(view=near_user, gt=addressing_user)
         フレーム 1.0 で quality_regime 誤り(view=BLOCK, gt=GOOD)
         フレーム 2.0 で scene_regime 誤り(view=MOVING, gt=STABLE)

    合計:
      t2_mode 誤り: 1
      t2_relation 誤り: 1
      t3_hypothesis 誤り: 0
      quality_regime 誤り: 1
      scene_regime 誤り: 1
    """
    return {
        "sc1": [
            make_trace_frame(0.0),
            make_trace_frame(1.0, view_overrides={"t2_mode": "conv_ongoing"}),
            make_trace_frame(2.0),
        ],
        "sc2": [
            make_trace_frame(0.0, view_overrides={"t2_relation": "near_user"}),
            make_trace_frame(1.0, view_overrides={"quality_regime": "BLOCK"}),
            make_trace_frame(2.0, view_overrides={"scene_regime": "MOVING"}),
        ],
    }


def canonical_records_for_trace():
    """trace_with_known_errors() / trace_perfect_2scenario() に対応する
    canonical GT レコード群（(scenario_id, ts) が突合可能）。

    trace の scenario 名 "sc1"/"sc2" を scenario_id とし、
    gt 層の各ラベルが canonical GT のフィールド値と一致するよう構成する。

    t2_mode / t2_relation は確率分布の argmax が trace gt ラベルと一致するよう設定する。
    t3_hypothesis / quality_regime / scene_regime は文字列フィールドで完全一致。
    """
    def _make_canonical_frame(ts, *, mode_argmax, relation_argmax,
                              hypothesis, quality_regime, scene_regime):
        frame = _frame(ts)
        # mode: argmax を mode_argmax に設定（他は 0.0）
        mode_dist = {k: 0.0 for k in T2_MODE_KEYS}
        mode_dist[mode_argmax] = 1.0
        frame["t2"]["mode"] = mode_dist
        # relations: argmax を relation_argmax に設定（他は 0.0）
        rel_dist = {k: 0.0 for k in T2_RELATIONS_KEYS}
        rel_dist[relation_argmax] = 1.0
        frame["t2"]["relations"] = rel_dist
        # t3 文字列フィールド
        frame["t3"]["hypothesis"] = hypothesis
        frame["t3"]["quality_regime"] = quality_regime
        frame["t3"]["scene_regime"] = scene_regime
        return frame

    sc1_frames = [
        _make_canonical_frame(0.0, mode_argmax="conv_request",
                              relation_argmax="addressing_user",
                              hypothesis="indoor_quiet",
                              quality_regime="GOOD", scene_regime="STABLE"),
        _make_canonical_frame(1.0, mode_argmax="conv_request",  # trace gt = conv_request
                              relation_argmax="addressing_user",
                              hypothesis="indoor_quiet",
                              quality_regime="GOOD", scene_regime="STABLE"),
        _make_canonical_frame(2.0, mode_argmax="conv_request",
                              relation_argmax="addressing_user",
                              hypothesis="indoor_quiet",
                              quality_regime="GOOD", scene_regime="STABLE"),
    ]
    sc2_frames = [
        _make_canonical_frame(0.0, mode_argmax="conv_request",
                              relation_argmax="addressing_user",  # trace gt = addressing_user
                              hypothesis="indoor_quiet",
                              quality_regime="GOOD", scene_regime="STABLE"),
        _make_canonical_frame(1.0, mode_argmax="conv_request",
                              relation_argmax="addressing_user",
                              hypothesis="indoor_quiet",
                              quality_regime="GOOD",   # trace gt = GOOD
                              scene_regime="STABLE"),
        _make_canonical_frame(2.0, mode_argmax="conv_request",
                              relation_argmax="addressing_user",
                              hypothesis="indoor_quiet",
                              quality_regime="GOOD",
                              scene_regime="STABLE"),  # trace gt = STABLE
    ]

    sc1_meta = {
        "scenario_id": "sc1",
        "source": {"repo": "local", "commit": "fixture-trace-v1",
                   "path": "scenarios/v021_core/sc1"},
        "parent_lineage_id": "sc1",
        "parents": [],
        "generation": 0,
        "split": "unassigned",
        "gt_origin": "ai_generated",
        "registered_at": "2026-06-12T00:00:00Z",
    }
    sc2_meta = copy.deepcopy(sc1_meta)
    sc2_meta["scenario_id"] = "sc2"
    sc2_meta["source"]["path"] = "scenarios/v021_core/sc2"
    sc2_meta["parent_lineage_id"] = "sc2"

    return [
        {"meta": sc1_meta,
         "gt": {"scenario_id": "sc1", "version": "1.0",
                "description": "trace fixture sc1", "frames": sc1_frames},
         "custom": {}},
        {"meta": sc2_meta,
         "gt": {"scenario_id": "sc2", "version": "1.0",
                "description": "trace fixture sc2", "frames": sc2_frames},
         "custom": {}},
    ]
