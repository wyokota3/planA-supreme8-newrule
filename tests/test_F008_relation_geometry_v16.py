"""ADR 0043(v1.6): relation を主トラックの range 幾何で忠実化(departing/near_user/unrelated 回収)。

relation は Tier-A rule_derived=観測幾何の決定的関数。主トラック(w_obs,-r_m 最大)の絶対 range と
Δr で分類。addressing は既存ロジックに委譲。w_obs/r_m は v1.4 入力にも在り version 非依存。
"""
from supreme import core


def _snap(ts, r, kind="barrier", w=0.6, links=None):
    if kind == "human":
        tracks = {"audio": [], "objects": [], "humans": [{"r_m": r, "w_obs": w, "speaking_prob": 0.0}]}
    else:
        tracks = {"audio": [], "objects": [{"type": kind, "r_m": r, "w_obs": w}], "humans": []}
    return {"version": "PSO-Snapshot/1.5", "ts": ts, "frame": "W2D",
            "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0}, "tracks": tracks,
            "links": links or [], "geom": {"min_TTC_s": 99.0, "overlap_path": False, "lane_alignment": False},
            "scene_state": {"QoS": 0.9, "latency_ms": 40}, "utter_events": []}


def _run(snaps):
    return core.run_supreme_scenarios({"s": snaps}, None)["s"]


def test_near_object_is_near_user():
    """主トラック r<=5 → near_user(approaching に優先)。"""
    v = _run([_snap(0.0, 2.0), _snap(0.5, 1.5)])
    assert all(x["t2_relation"] == "near_user" for x in v)


def test_receding_is_departing():
    """range 増(後退)→ departing。"""
    v = _run([_snap(0.0, 10.0), _snap(0.5, 14.0), _snap(1.0, 18.0)])
    # 初手は前 range 無で departing 判定不可・以降は departing。
    assert v[1]["t2_relation"] == "departing" and v[2]["t2_relation"] == "departing"


def test_approaching_far_is_approaching():
    """range 減(接近・遠方発)→ approaching。"""
    v = _run([_snap(0.0, 30.0), _snap(0.5, 26.0), _snap(1.0, 22.0)])
    assert v[1]["t2_relation"] == "approaching" and v[2]["t2_relation"] == "approaching"


def test_far_static_is_unrelated():
    """遠方(>15)・静止・link 無 → unrelated。"""
    v = _run([_snap(0.0, 40.0), _snap(0.5, 40.0)])
    assert all(x["t2_relation"] == "unrelated" for x in v)


def test_addressing_link_defers_to_existing():
    """addressing link は既存ロジックへ委譲(addressing_user・幾何 override しない)。"""
    links = [{"type": "addressing", "score": 0.8}]
    v = _run([_snap(0.0, 40.0, links=links), _snap(0.5, 40.0, links=links)])
    assert all(x["t2_relation"] == "addressing_user" for x in v)
