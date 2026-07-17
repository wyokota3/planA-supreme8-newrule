"""v1.5(C-1b)/ADR 0047: 低 QoS → uncertain mode(欠落クラス回収)。

ADR 0047(mode 厳密化)で GT(gt_derive.mode_seq)を厳密適用。uncertain は生 QoS BLOCK(q<0.55)で発火し、
QoS は v1.4 可観測のため episode(v1.5)に依らず v1.4 入力でも uncertain になる(旧 episode ゲートは撤廃)。
"""
from supreme import core


def _snap(ts, qos, episode=True):
    s = {"version": "PSO-Snapshot/1.5", "ts": ts, "frame": "W2D",
         "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0},
         "tracks": {"audio": [], "objects": [{"type": "barrier", "r_m": 10.0, "w_obs": 0.5}], "humans": []},
         "links": [], "geom": {"min_TTC_s": 99.0, "overlap_path": False, "lane_alignment": False},
         "scene_state": {"QoS": qos, "latency_ms": 40}, "utter_events": []}
    if episode:
        s["episode"] = {"episode_id": "e", "elapsed_s": ts, "frame_index": int(ts * 2),
                        "turn_count": 0, "speech_ratio": 0.0, "hazard_trend": 0.0, "approach_ratio": 0.0}
    return s


def test_v15_low_qos_forces_uncertain_mode():
    v = core.run_supreme_scenarios({"s": [_snap(0.0, 0.3), _snap(0.5, 0.3)]}, None)
    assert all(x["t2_mode"] == "uncertain" for x in v["s"])


def test_v15_high_qos_not_uncertain():
    v = core.run_supreme_scenarios({"s": [_snap(0.0, 0.9), _snap(0.5, 0.9)]}, None)
    assert all(x["t2_mode"] != "uncertain" for x in v["s"])


def test_v14_low_qos_is_uncertain_no_episode_gate():
    """ADR 0047: 生 QoS BLOCK は v1.4 可観測 → episode 無(v1.4)でも GT 通り uncertain。

    旧実装は uncertain を episode(v1.5)でゲートしていたが、strict mode_seq は v1.4/v1.5 双方に GT 規則を
    適用する(v1.5 は新情報ゼロ=自前観測で同値)。"""
    v = core.run_supreme_scenarios({"s": [_snap(0.0, 0.3, episode=False), _snap(0.5, 0.3, episode=False)]}, None)
    assert all(x["t2_mode"] == "uncertain" for x in v["s"])
