"""T-Scene v1.5(C-1b): episode 集約 stability → scene_regime。後方互換(stability 無=HGF 経路)。"""
from supreme import core
from supreme import scene as scene_mod


def _snap(qos, qos_trend):
    return {"scene_state": {"QoS": qos,
            "stability": {"qos_trend": qos_trend, "track_churn": 0.0,
                          "change_point": {"score": 0.0, "frames_since": 0}}}}


def test_v15_stable_when_no_decline():
    snaps = [_snap(0.9, 0.0), _snap(0.9, -0.02)]
    seq = core._scene_regime_sequence([0.0, 0.0], None, snaps)
    assert seq == [scene_mod.STABLE, scene_mod.STABLE]


def test_v15_degrading_low_mean_qos():
    snaps = [_snap(0.5, -0.4), _snap(0.4, -0.4)]  # 降下 ∧ 平均 QoS 0.45<0.5
    seq = core._scene_regime_sequence([0.0, 0.0], None, snaps)
    assert seq == [scene_mod.DEGRADING, scene_mod.DEGRADING]


def test_v15_changing_mid_qos_declining():
    snaps = [_snap(0.7, -0.3), _snap(0.6, -0.3)]  # 降下 ∧ 平均 QoS 0.65>=0.5
    seq = core._scene_regime_sequence([0.0, 0.0], None, snaps)
    assert seq == [scene_mod.CHANGING, scene_mod.CHANGING]


def test_v15_episode_constant_all_frames_same():
    """scene_regime はシナリオ内一定で出力される(全フレーム同一)。"""
    snaps = [_snap(0.9, 0.0), _snap(0.6, -0.3), _snap(0.4, -0.4)]
    seq = core._scene_regime_sequence([0.0, 0.0, 0.0], None, snaps)
    assert len(set(seq)) == 1


def test_v14_no_stability_uses_hgf_path():
    """stability 無(v1.4)は episode 上書きせず HGF 経路。"""
    snaps = [{"scene_state": {"QoS": 0.9}}, {"scene_state": {"QoS": 0.9}}]
    seq = core._scene_regime_sequence([1.0, 1.0], None, snaps)
    assert all(r in (scene_mod.STABLE, scene_mod.CHANGING, scene_mod.DEGRADING) for r in seq)


def test_v14_snaps_none_unchanged():
    """snaps=None(従来呼び出し)は完全に従来挙動。"""
    seq = core._scene_regime_sequence([1.0, 1.0], None, None)
    assert len(seq) == 2
