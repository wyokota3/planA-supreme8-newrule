# -*- coding: utf-8 -*-
"""F-020: T2 本来型 NeuPSL の単体テスト(supreme3・ADR 0052-s3)。

観点: Łukasiewicz/単体射影の数理、決定性、事前重みでのルール優先(危険→emergency と
層間整合)、学習の決定性と「学習が事前重みを下回らない」こと(小規模合成データ)。
"""
from supreme import neupsl


_ZERO = {k: 0.0 for k in
         ["siren", "alarm", "vehicle", "speech", "speaking", "range_n", "near3",
          "humans_n", "objects_n", "call_user", "addr_link", "spk_link",
          "risk_danger", "risk_caution", "approaching", "h_q"]}


def _f(**kw):
    d = dict(_ZERO)
    d.update(kw)
    return d


def test_simplex_projection_properties():
    for v in ([0.5, 0.5, 0.5], [2.0, 0.0, 0.0], [-1.0, 0.2, 0.3], [0.0] * 9):
        p = neupsl._project_simplex(list(v))
        assert all(x >= 0.0 for x in p)
        assert abs(sum(p) - 1.0) < 1e-9
    # 既に単体上なら不変
    p = neupsl._project_simplex([0.2, 0.3, 0.5])
    assert all(abs(a - b) < 1e-9 for a, b in zip(p, [0.2, 0.3, 0.5]))


def test_inference_is_deterministic():
    frames = [_f(risk_danger=1.0, alarm=1.0, h_q=0.9), _f(h_q=0.9), _f(h_q=0.9)]
    out1 = neupsl.infer_scenario(frames)
    out2 = neupsl.infer_scenario(frames)
    assert out1 == out2


def test_prior_danger_fires_emergency_and_alarm_role():
    """危険(T0)→ emergency の直結ルールと、層間整合(emergency → source_alarm)。"""
    out = neupsl.infer_scenario([_f(risk_danger=1.0, alarm=1.0, h_q=0.9)])
    assert out[0]["mode"] == "emergency"
    assert out[0]["role"] == "source_alarm"


def test_default_params_count_fixed():
    p = neupsl.default_params()
    assert p.learnable_param_count() == 353


def test_fit_deterministic_and_not_worse_than_prior():
    """小規模合成データで、fit の決定性と『学習 ≥ 事前重み』を確認する。"""
    conv = _f(speech=1.0, speaking=0.9, range_n=0.9, near3=1.0, spk_link=1.0, h_q=0.9)
    quiet = _f(h_q=0.9)
    danger = _f(risk_danger=1.0, alarm=1.0, h_q=0.9)
    gt_conv = {"mode": "conv_ongoing", "role": "source_speech", "rel": "near_user"}
    gt_quiet = {"mode": "quiet_standby", "role": "unknown", "rel": "grouped"}
    gt_danger = {"mode": "emergency", "role": "source_alarm", "rel": "grouped"}
    scens = [([conv, conv], [gt_conv, gt_conv]),
             ([quiet, quiet], [gt_quiet, gt_quiet]),
             ([danger, danger], [gt_danger, gt_danger])] * 6
    p1 = neupsl.fit(scens, epochs=3)
    p2 = neupsl.fit(scens, epochs=3)
    assert p1.weights == p2.weights
    assert all(p1.mlps[k] == p2.mlps[k] for k in p1.mlps)

    def acc(params):
        c = t = 0
        for feats, gts in scens:
            out = neupsl.infer_scenario(feats, params)
            for i, g in enumerate(gts):
                for layer in ("mode", "role", "rel"):
                    t += 1
                    c += out[i][layer] == g[layer]
        return c / t

    assert acc(p1) >= acc(neupsl.default_params())


def test_persistence_rule_is_grounded_per_frame_pair():
    """時間持続ルールは (フレーム数 − 1) × モード数ぶん接地される。"""
    inst = neupsl._rule_instances(3)
    persist = [x for x in inst if x[0] == "t_persist_mode"]
    assert len(persist) == 2 * len(neupsl.MODES)
