"""ADR 0050: strict GT-conformance ゲート(config `strict_gt_conformance`・既定 True)。

strict 系オーバーライド(ADR 0043〜0048 = GT 生成器 gt_derive.py の規則写し・ADR 0049 で
能力指標としては循環と撤回)を config でゲートする:
  - True(既定) = 現行挙動を完全維持(spec-conformance モード・後方互換)。
  - False      = strict をスキップし、strict 導入前(ADR 0042 まで)の観測ベース経路
                 (quality=quality.classify(h_q,vol) / risk=t0.risk_tier(track) /
                  t1=t1.t1_state+ADR 0038 補正 / mode=logits→hysteresis+v1.5 uncertain /
                  role=role.classify(evidence) / relation=relation.classify(evidence))
                 へフォールバックする。能力評価・対外比較では False 必須(ADR 0049/0050)。

検証: (a) 既定=ON が現行出力と同一(config 省略・空 dict・明示 True の3形が一致)、
(b) OFF で strict 対象6層それぞれの出力が旧経路になる(fixture 上で strict と異なる)、
(c) OFF でも決定的・クラッシュなし。依存は stdlib のみ・全フィクスチャは決定的 dict リテラル。
"""

from supreme import core
from supreme import neupsl as neupsl_mod
from supreme import t0 as t0_mod


_OFF = {"strict_gt_conformance": False}


def _snap(ts, tracks=None, geom=None, scene_state=None, links=None, utter=None):
    """PSO-Snapshot/1.4 の最小フレーム(決定的 dict リテラル)。"""
    s = {
        "version": "PSO-Snapshot/1.4",
        "ts": ts,
        "frame": "W2D",
        "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0},
        "tracks": tracks or {"audio": [], "objects": [], "humans": []},
        "links": links or [],
        "utter_events": utter or [],
    }
    if geom is not None:
        s["geom"] = geom
    if scene_state is not None:
        s["scene_state"] = scene_state
    return s


def _obj(r_m, kind="barrier", w_obs=0.9):
    return {"audio": [], "objects": [{"type": kind, "r_m": r_m, "w_obs": w_obs}], "humans": []}


# --- 差分 fixture 群(strict ON と OFF で該当層の出力が異なる決定的シナリオ)---

def _trackless_caution_snaps():
    """ADR 0048 の署名(pw-021-seal-07): track ゼロ・geom.min_TTC_s=6.0。

    strict: geom TTC を track 非依存で読む → caution(mode は side_rear_caution)。
    旧経路: t0.risk_tier は track 0 件で安全側 info に縮退 → info。
    """
    return [
        _snap(0.0, geom={"min_TTC_s": 6.0}, scene_state={"QoS": 0.95, "latency_ms": 40}),
        _snap(0.5, geom={"min_TTC_s": 6.0}, scene_state={"QoS": 0.95, "latency_ms": 40}),
    ]


def _qos_mid_snaps():
    """QoS=0.85(中位)。strict: 生 QoS 規則で DEGRADED(0.55<=q<0.90)。

    旧経路: quality.classify(h_q, vol)。高 QoS 寄り観測式で h_q>=0.93・vol<0.01 → GOOD。
    """
    return [
        _snap(t, tracks=_obj(40.0), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.85, "latency_ms": 40})
        for t in (0.0, 0.5, 1.0)
    ]


def _barrier_snaps():
    """barrier object(w_obs 0.9)のみ。strict role: salient 種別 → source_object。

    旧経路: role.classify(evidence) は siren/alarm/vehicle/speech 証拠ゼロ → unknown。
    """
    return [
        _snap(0.0, tracks=_obj(6.0), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}),
        _snap(0.5, tracks=_obj(6.0), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}),
    ]


def _far_static_snaps():
    """遠方(r=40)静止・link 無。strict relation: range 幾何 → unrelated。

    旧経路: relation.classify(evidence) は 4 クラス語彙で無証拠既定 → grouped。
    """
    return [
        _snap(0.0, tracks=_obj(40.0, w_obs=0.6), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}),
        _snap(0.5, tracks=_obj(40.0, w_obs=0.6), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}),
    ]


def _receding_snaps():
    """後退軌跡(r: 10→14→18・ttc=99)。strict t1: range 幾何 → [approach, depart, depart]。

    旧経路: t1.t1_state は ttc=99>=12 で approach 不成立 → 全フレーム idle。
    """
    return [
        _snap(0.0, tracks=_obj(10.0, w_obs=0.6), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}),
        _snap(0.5, tracks=_obj(14.0, w_obs=0.6), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}),
        _snap(1.0, tracks=_obj(18.0, w_obs=0.6), geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}),
    ]


def _speaking_link_no_utter_snaps():
    """speaking link 在り・utter_events 無し。strict mode: GT 規則は utter ∧ link 必須 →
    conv 不成立 → salient 在り → surround_activity。

    旧経路(ADR 0040): speaking link 単独で conv_ongoing が立つ → conv_ongoing。
    """
    tracks = {"audio": [{"type": "speech", "r_m": 6.0, "w_obs": 0.9}],
              "objects": [], "humans": []}
    links = [{"type": "speaking", "score": 0.9}]
    return [
        _snap(0.0, tracks=tracks, geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}, links=list(links)),
        _snap(0.5, tracks=tracks, geom={"min_TTC_s": 99.0},
              scene_state={"QoS": 0.95, "latency_ms": 40}, links=list(links)),
    ]


def _all_fixture_scenarios():
    """全差分 fixture を run_supreme_scenarios 形にまとめる(既定=ON 同一性の検証用)。"""
    return {
        "trackless_caution": _trackless_caution_snaps(),
        "qos_mid": _qos_mid_snaps(),
        "barrier": _barrier_snaps(),
        "far_static": _far_static_snaps(),
        "receding": _receding_snaps(),
        "speaking_link_no_utter": _speaking_link_no_utter_snaps(),
    }


# ===========================================================================
# (a) 既定=ON: config 省略・空 dict・明示 True が現行出力と同一(後方互換)
# ===========================================================================

def test_default_on_identical_to_explicit_true_and_empty_config():
    """config 省略 / {} / {"strict_gt_conformance": True} の3形が完全一致(既定 ON)。"""
    scenarios = _all_fixture_scenarios()
    default = core.run_supreme_scenarios(scenarios)
    empty = core.run_supreme_scenarios(scenarios, config={})
    explicit = core.run_supreme_scenarios(scenarios, config={"strict_gt_conformance": True})
    assert default == empty == explicit


def test_default_on_still_applies_strict_overrides():
    """既定(ON)は strict 挙動そのもの(ADR 0048 署名: track ゼロ・ttc=6 → caution)。"""
    views = core.run_supreme(_trackless_caution_snaps())
    assert [v["risk_tier"] for v in views] == ["caution", "caution"]
    assert [v["t2_mode"] for v in views] == ["side_rear_caution", "side_rear_caution"]


# ===========================================================================
# (b) OFF: strict 対象6層の出力が旧経路になる(fixture 上で strict と異なる)
# ===========================================================================

def test_off_risk_falls_back_to_track_based_t0():
    """OFF risk: track ゼロは t0.risk_tier の安全側 info(strict は geom TTC で caution)。"""
    snaps = _trackless_caution_snaps()
    on = core.run_supreme(snaps)
    off = core.run_supreme(snaps, config=_OFF)
    assert [v["risk_tier"] for v in on] == ["caution", "caution"]
    assert [v["risk_tier"] for v in off] == ["info", "info"]
    # 旧経路そのもの: t0.risk_tier(_t0_tracks(snap)) と一致。
    for v, snap in zip(off, snaps):
        assert v["risk_tier"] == t0_mod.risk_tier(core._t0_tracks(snap))


def test_off_quality_falls_back_to_hq_vol_classify():
    """OFF quality: quality.classify(h_q, vol)(strict は生 QoS 規則で DEGRADED)。"""
    snaps = _qos_mid_snaps()
    on = core.run_supreme(snaps)
    off = core.run_supreme(snaps, config=_OFF)
    assert [v["quality_regime"] for v in on] == ["DEGRADED"] * 3
    assert [v["quality_regime"] for v in off] == ["GOOD"] * 3


def test_off_role_uses_neupsl_path():
    """supreme3: OFF の role は NeuPSL(結合 MAP)の出力(strict は salient 種別で source_object)。"""
    snaps = _barrier_snaps()
    on = core.run_supreme(snaps)
    off = core.run_supreme(snaps, config=_OFF)
    assert [v["t2_role"] for v in on] == ["source_object", "source_object"]
    expected = neupsl_mod.infer_scenario(core._neupsl_inputs_from_scenario(snaps))
    assert [v["t2_role"] for v in off] == [e["role"] for e in expected]


def test_off_relation_uses_neupsl_path():
    """supreme3: OFF の relation は NeuPSL の出力(strict は range 幾何で unrelated)。"""
    snaps = _far_static_snaps()
    on = core.run_supreme(snaps)
    off = core.run_supreme(snaps, config=_OFF)
    assert [v["t2_relation"] for v in on] == ["unrelated", "unrelated"]
    expected = neupsl_mod.infer_scenario(core._neupsl_inputs_from_scenario(snaps))
    assert [v["t2_relation"] for v in off] == [e["rel"] for e in expected]


def test_off_t1_falls_back_to_state_machine():
    """OFF t1: t1.t1_state 経路(ttc=99 は approach 不成立 → idle。strict は range 幾何で
    approach/depart)。"""
    snaps = _receding_snaps()
    on = core.run_supreme(snaps)
    off = core.run_supreme(snaps, config=_OFF)
    assert [v["t1_state"] for v in on] == ["approach", "depart", "depart"]
    assert [v["t1_state"] for v in off] == ["idle", "idle", "idle"]


def test_off_mode_uses_neupsl_path():
    """supreme3: OFF の mode は NeuPSL(時間持続ルール込みの結合 MAP)の出力。
    strict は GT 規則(utter ∧ link 必須)で conv 不成立 → surround_activity。"""
    snaps = _speaking_link_no_utter_snaps()
    on = core.run_supreme(snaps)
    off = core.run_supreme(snaps, config=_OFF)
    assert [v["t2_mode"] for v in on] == ["surround_activity", "surround_activity"]
    expected = neupsl_mod.infer_scenario(core._neupsl_inputs_from_scenario(snaps))
    assert [v["t2_mode"] for v in off] == [e["mode"] for e in expected]


# ===========================================================================
# (c) OFF でも決定的・クラッシュなし・語彙/形状の契約維持
# ===========================================================================

def test_off_deterministic_and_well_formed():
    """OFF は同一入力で 2 回 run が完全一致(決定的)し、8 層 view 形状を保つ。"""
    scenarios = _all_fixture_scenarios()
    first = core.run_supreme_scenarios(scenarios, config=_OFF)
    second = core.run_supreme_scenarios(scenarios, config=_OFF)
    assert first == second
    for sid, snaps in scenarios.items():
        views = first[sid]
        assert len(views) == len(snaps)
        for view in views:
            assert set(view.keys()) == set(core.VIEW_LAYERS)


def test_off_config_passes_through_scenarios_and_build_trace():
    """config は run_supreme_scenarios / build_trace を透過する(評価経路の自動透過)。"""
    scenarios = {"s": _trackless_caution_snaps()}
    off_views = core.run_supreme_scenarios(scenarios, config=_OFF)["s"]
    assert [v["risk_tier"] for v in off_views] == ["info", "info"]
    # build_trace(gt 省略時は view を gt に写す)も config を透過する。
    trace = core.build_trace(scenarios, {}, config=_OFF)
    assert [f["view"]["risk_tier"] for f in trace["s"]] == ["info", "info"]


def test_off_differs_from_on_only_where_strict_layers_change():
    """同一 fixture 群で ON/OFF を全層比較: strict 対象層に差分が実在し、非対象層
    (scene_regime)は本 fixture 群で不変(ゲートの波及範囲が strict 系に限られる)。"""
    scenarios = _all_fixture_scenarios()
    on = core.run_supreme_scenarios(scenarios)
    off = core.run_supreme_scenarios(scenarios, config=_OFF)
    changed = set()
    for sid in scenarios:
        for von, voff in zip(on[sid], off[sid]):
            for layer in core.VIEW_LAYERS:
                if von[layer] != voff[layer]:
                    changed.add(layer)
    # strict 対象 6 層すべてに差分 fixture が存在する(ゲートが実際に効いている)。
    assert {"risk_tier", "t1_state", "t2_mode", "t2_role",
            "t2_relation", "quality_regime"} <= changed
    # scene_regime は strict 対象外(ゲートで変えない)。
    assert "scene_regime" not in changed
