"""ADR 0042: caution を salient kind で分岐(vehicle→forward / object・human→side_rear / 他→alert)。

side_rear_caution は旧実装で emit 経路ゼロ(死クラス)だった。salience 不在(v1.4)は None→alert_required
で従来挙動を保つ(後方互換)。
"""
from supreme import core


def _snap(ts, kind, ttc=5.0, salience=0.9, with_salience=True, episode=True):
    audio, objects, humans = [], [], []
    if kind == "object":
        objects = [{"type": "barrier", "r_m": 8.0, "theta_deg": 135.0, "w_obs": 0.6}]
    elif kind == "vehicle":
        objects = [{"type": "vehicle", "r_m": 8.0, "w_obs": 0.7}]
    elif kind == "human":
        humans = [{"r_m": 8.0, "w_obs": 0.6, "speaking_prob": 0.0}]
    elif kind == "alarm":
        audio = [{"type": "alarm", "r_m": 12.0, "w_obs": 0.75}]
    if with_salience:
        for t in audio + objects + humans:
            t["salience"] = salience
    s = {"version": "PSO-Snapshot/1.5" if with_salience else "PSO-Snapshot/1.4", "ts": ts, "frame": "W2D",
         "origin": {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0},
         "tracks": {"audio": audio, "objects": objects, "humans": humans},
         "links": [], "geom": {"min_TTC_s": ttc, "overlap_path": False, "lane_alignment": False},
         "scene_state": {"QoS": 0.9, "latency_ms": 40}, "utter_events": []}
    if episode:
        s["episode"] = {"episode_id": "e", "elapsed_s": ts, "frame_index": int(ts * 2),
                        "turn_count": 0, "speech_ratio": 0.0, "hazard_trend": 0.0, "approach_ratio": 0.0}
    return s


def _run(kind, **kw):
    return core.run_supreme_scenarios({"s": [_snap(0.0, kind, **kw), _snap(0.5, kind, **kw)]}, None)["s"]


def test_caution_object_is_side_rear():
    v = _run("object")
    assert all(x["t2_mode"] == "side_rear_caution" for x in v)


def test_caution_human_is_side_rear():
    v = _run("human")
    assert all(x["t2_mode"] == "side_rear_caution" for x in v)


def test_caution_vehicle_is_forward_caution():
    v = _run("vehicle")
    assert all(x["t2_mode"] == "forward_caution" for x in v)


def test_caution_alarm_is_alert_required():
    v = _run("alarm")
    assert all(x["t2_mode"] == "alert_required" for x in v)


def test_v14_no_salience_caution_object_is_side_rear():
    """ADR 0047: salient は w_obs/r_m で選ぶ(v1.5 salience フィールド不要)。v1.4・salience 無・episode 無でも
    caution の object salient は GT 通り side_rear_caution(旧 alert_required fallback は撤廃)。"""
    v = core.run_supreme_scenarios(
        {"s": [_snap(0.0, "object", with_salience=False, episode=False),
               _snap(0.5, "object", with_salience=False, episode=False)]}, None)["s"]
    assert all(x["t2_mode"] == "side_rear_caution" for x in v)
