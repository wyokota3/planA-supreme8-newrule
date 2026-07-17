"""t1_state の v1.5/v1.6 挙動。

v1.5(ADR 0038)は episode.approach_ratio で t1 を補正していたが、v1.6(ADR 0044)で
**salient range 軌跡(Δr)が authoritative**(GT gt_derive.t1_state_seq の忠実化)に更新。
range が取れる限り Δr が t1 を支配する(approach_ratio 補正は salient 無のフォールバック)。
range/w_obs は v1.4 入力にも在り version 非依存。
"""
from supreme import core


def _snap(ts, r, ttc=5.0, episode=True, approach_ratio=0.0, hazard=0.0):
    s = {"version": "PSO-Snapshot/1.5", "ts": ts, "frame": "W2D",
         "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0},
         "tracks": {"audio": [], "objects": [{"type": "vehicle", "r_m": r, "w_obs": 0.7}], "humans": []},
         "links": [], "geom": {"min_TTC_s": ttc, "overlap_path": False, "lane_alignment": False},
         "scene_state": {"QoS": 0.9, "latency_ms": 40}, "utter_events": []}
    if episode:
        s["episode"] = {"episode_id": "e", "elapsed_s": ts, "frame_index": int(ts * 2),
                        "turn_count": 0, "speech_ratio": 0.0, "hazard_trend": hazard,
                        "approach_ratio": approach_ratio}
    return s


def _run(rs, **kw):
    return core.run_supreme_scenarios({"s": [_snap(i * 0.5, r, **kw) for i, r in enumerate(rs)]}, None)["s"]


def test_v16_decreasing_range_is_approach():
    """range 減少(実接近)→ approach(Δr<0)。"""
    v = _run([12.0, 8.0, 5.0])
    assert all(x["t1_state"] == "approach" for x in v)


def test_v16_increasing_far_range_is_depart():
    """遠方で range 増加(後退)→ depart(最接近が近くないので pass でない)。"""
    v = _run([20.0, 24.0, 28.0])
    assert v[1]["t1_state"] == "depart" and v[2]["t1_state"] == "depart"


def test_v16_constant_far_range_is_idle():
    """遠方・静止 → idle(Δr≈0)。"""
    v = _run([20.0, 20.0, 20.0])
    assert all(x["t1_state"] == "idle" for x in v)


def test_v16_close_pass_is_pass():
    """接近して最接近(≤8m)直後に後退 → その1フレームは pass。"""
    v = _run([12.0, 4.0, 9.0])
    assert v[2]["t1_state"] == "pass"


def test_v16_geometry_overrides_contradictory_approach_ratio():
    """range 静止だが approach_ratio 高 → 幾何(idle 系)が支配(approach_ratio に従わない)。"""
    v = _run([20.0, 20.0], approach_ratio=0.9)
    assert all(x["t1_state"] != "approach" for x in v)


def test_v14_no_episode_geometry_applies():
    """episode 無(v1.4)でも range 幾何は version 非依存で作用(接近→approach)。"""
    v = _run([12.0, 8.0, 5.0], episode=False)
    assert all(x["t1_state"] == "approach" for x in v)
