"""T-T3 v1.5(C-1a): episode.speech_ratio>=0.7 → conv_participating(会話×危険でも保持)。後方互換。"""
from supreme import core


def _snap(ts, speech_ratio=None):
    s = {"version": "PSO-Snapshot/1.5", "ts": ts, "frame": "W2D",
         "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0},
         "tracks": {"audio": [{"type": "alarm", "r_m": 5.0, "w_obs": 0.7}], "objects": [], "humans": []},
         "links": [], "geom": {"min_TTC_s": 1.0, "overlap_path": False, "lane_alignment": False},
         "scene_state": {"QoS": 0.9, "latency_ms": 40}, "utter_events": []}
    if speech_ratio is not None:
        s["episode"] = {"episode_id": "e", "elapsed_s": ts, "frame_index": int(ts * 2),
                        "turn_count": 3, "speech_ratio": speech_ratio,
                        "hazard_trend": 0.0, "approach_ratio": 0.0}
    return s


def test_v15_high_speech_ratio_forces_conv_participating():
    """min_TTC=1.0(danger)→mode=emergency でも、speech_ratio 高なら t3=conv_participating。"""
    v = core.run_supreme_scenarios({"s": [_snap(0.0, 0.9), _snap(0.5, 0.9)]}, None)
    assert all(x["t3_hypothesis"] == "conv_participating" for x in v["s"])


def test_v15_low_speech_ratio_not_forced():
    v = core.run_supreme_scenarios({"s": [_snap(0.0, 0.2), _snap(0.5, 0.2)]}, None)
    assert all(x["t3_hypothesis"] != "conv_participating" for x in v["s"])


def test_v14_no_episode_unchanged():
    """episode 無(v1.4)は上書きせず(emergency→alert 系のまま)。"""
    v = core.run_supreme_scenarios({"s": [_snap(0.0, None), _snap(0.5, None)]}, None)
    assert all(x["t3_hypothesis"] != "conv_participating" for x in v["s"])


def _snap_ep(ts, speech=0.0, qos=0.9, approach=0.0):
    s = _snap(ts, None)
    s["scene_state"]["QoS"] = qos
    s["episode"] = {"episode_id": "e", "elapsed_s": ts, "frame_index": int(ts * 2),
                    "turn_count": 0, "speech_ratio": speech, "hazard_trend": 0.0,
                    "approach_ratio": approach}
    return s


def test_v15_low_qos_forces_uncertain_context():
    """平均 QoS < 0.4(観測劣化)→ uncertain_context。"""
    v = core.run_supreme_scenarios({"s": [_snap_ep(0.0, qos=0.3), _snap_ep(0.5, qos=0.3)]}, None)
    assert all(x["t3_hypothesis"] == "uncertain_context" for x in v["s"])


def test_v15_high_approach_forces_traffic_unstable():
    """平均 approach_ratio >= 0.65(接近継続)→ traffic_unstable。"""
    v = core.run_supreme_scenarios({"s": [_snap_ep(0.0, approach=0.8), _snap_ep(0.5, approach=0.8)]}, None)
    assert all(x["t3_hypothesis"] == "traffic_unstable" for x in v["s"])


def test_v15_t3_priority_speech_over_qos_approach():
    """優先順: 会話(speech) が低 QoS/接近より先。"""
    v = core.run_supreme_scenarios({"s": [_snap_ep(0.0, speech=0.9, qos=0.3, approach=0.8)]}, None)
    assert v["s"][0]["t3_hypothesis"] == "conv_participating"
