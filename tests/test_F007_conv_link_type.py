"""ADR 0040/0047: conv 種別を link type で分離(speaking→conv_ongoing / addressing→conv_request)。

ADR 0047(mode 厳密化)で GT(gt_derive.mode_seq)を厳密適用: conv は `utter_events 在り ∧
(speaking|addressing link)` で発火する(link は v1.4 入力にも在るため v1.4/v1.5 双方で発火・episode 不要)。
GT に call_user 単独の conv fallback は無い(utter だけ・link 無は conv にならない)。_snap は会話発生を
表す utter_events を既定で持たせる(GT の conv 前提)。
"""
from supreme import core


def _snap(ts, links=None, utter=None, qos=0.9, version="PSO-Snapshot/1.5", episode=True):
    s = {"version": version, "ts": ts, "frame": "W2D",
         "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0},
         "tracks": {"audio": [], "objects": [], "humans": [{"id": "H1", "r_m": 4.0}]},
         "links": links or [], "geom": {"min_TTC_s": 99.0, "overlap_path": False, "lane_alignment": False},
         "scene_state": {"QoS": qos, "latency_ms": 40},
         "utter_events": utter if utter is not None else [{"id": "u", "speaker": "H1"}]}
    if episode:
        s["episode"] = {"episode_id": "e", "elapsed_s": ts, "frame_index": int(ts * 2),
                        "turn_count": 0, "speech_ratio": 0.0, "hazard_trend": 0.0, "approach_ratio": 0.0}
    return s


def _link(t, score=0.9):
    return {"from": "A", "to": "H1", "type": t, "score": score}


def test_speaking_link_is_conv_ongoing():
    links = [_link("speaking")]
    v = core.run_supreme_scenarios({"s": [_snap(0.0, links), _snap(0.5, links)]}, None)
    assert all(x["t2_mode"] == "conv_ongoing" for x in v["s"])


def test_addressing_link_is_conv_request():
    links = [_link("addressing")]
    v = core.run_supreme_scenarios({"s": [_snap(0.0, links), _snap(0.5, links)]}, None)
    assert all(x["t2_mode"] == "conv_request" for x in v["s"])


def test_addressing_priority_over_speaking():
    """addressing と speaking が同居 → conv_request(addressing 優先)。"""
    links = [_link("addressing"), _link("speaking")]
    v = core.run_supreme_scenarios({"s": [_snap(0.0, links), _snap(0.5, links)]}, None)
    assert all(x["t2_mode"] == "conv_request" for x in v["s"])


def test_conv_link_not_stolen_by_low_qos_uncertain():
    """v1.5: conv link が在れば低 QoS でも uncertain に奪われない。"""
    links = [_link("speaking")]
    v = core.run_supreme_scenarios({"s": [_snap(0.0, links, qos=0.3), _snap(0.5, links, qos=0.3)]}, None)
    assert all(x["t2_mode"] == "conv_ongoing" for x in v["s"])


def test_v14_conv_link_no_episode_is_conv():
    """ADR 0047: v1.4(episode 無)でも link+utter が在れば GT 通り conv が発火(episode ゲート無し)。"""
    links = [_link("addressing")]
    utter = [{"id": "u"}]
    v = core.run_supreme_scenarios(
        {"s": [_snap(0.0, links, utter, version="PSO-Snapshot/1.4", episode=False),
               _snap(0.5, links, utter, version="PSO-Snapshot/1.4", episode=False)]}, None)
    assert all(x["t2_mode"] == "conv_request" for x in v["s"])


def test_v14_call_user_without_link_is_not_conv():
    """ADR 0047: GT mode_seq に call_user 単独の conv fallback は無い(utter だけ・link 無は conv にならない)。"""
    utter = [{"call_user": True}]
    v = core.run_supreme_scenarios(
        {"s": [_snap(0.0, None, utter, version="PSO-Snapshot/1.4", episode=False),
               _snap(0.5, None, utter, version="PSO-Snapshot/1.4", episode=False)]}, None)
    assert all(x["t2_mode"] not in ("conv_request", "conv_ongoing") for x in v["s"])
