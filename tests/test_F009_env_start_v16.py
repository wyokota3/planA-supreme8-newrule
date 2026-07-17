"""ADR 0041(v1.6): QoS 振動(detrend 残差分散)→ env_start。単調降下/平坦は env_start でない。後方互換。"""
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


def _run(qos_seq, episode=True):
    snaps = [_snap(i * 0.5, q, episode) for i, q in enumerate(qos_seq)]
    return core.run_supreme_scenarios({"s": snaps}, None)["s"]


def test_oscillating_qos_is_env_start():
    """QoS 振動(平均回帰)→ env_start。"""
    v = _run([0.72, 0.47, 0.72, 0.47, 0.72])
    assert all(x["t3_hypothesis"] == "env_start" for x in v)


def test_monotonic_decline_not_env_start():
    """単調降下(detrend 残差≈0)→ env_start でない(hazard 領域・写さない)。"""
    v = _run([0.95, 0.80, 0.65, 0.50])
    assert all(x["t3_hypothesis"] != "env_start" for x in v)


def test_flat_qos_not_env_start():
    """平坦 QoS → env_start でない。"""
    v = _run([0.9, 0.9, 0.9, 0.9])
    assert all(x["t3_hypothesis"] != "env_start" for x in v)


def test_v14_no_episode_no_env_start_override():
    """episode 無(v1.4)は振動でも env_start 上書きしない(後方互換)。"""
    v = _run([0.72, 0.47, 0.72, 0.47, 0.72], episode=False)
    assert all(x["t3_hypothesis"] != "env_start" for x in v)
