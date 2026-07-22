"""F-015: situations_v1 アダプタ(situations_common)の単体テスト。

合成フィクスチャのみで検証し、外部データ(_audit-harness-retrofit)へは依存しない
(データルートが在るときだけ軽い統合スモークを追加実行し、無ければ skip)。

検証観点:
  - preflight が 4 種の契約違反(bad_version / ts_regression / frame_count_mismatch /
    type_break)を各々検出し、クリーンなシナリオは通す。
  - version は preflight でも prepare_snaps でも**書き換えない**(bad_version 洗浄の禁止)。
  - gt_view がラベル形(format: label)を 8 層へ写し、補助 t2.hazard / t2.dynamics を無視する。
    quality_regime / scene_regime は t3 配下から取る。
  - prepare_snaps が欠落 geom のみ min_TTC_s=999.0 で補完し、原本を破壊しない。
"""

import os
import sys

import pytest

# reports 配下のキャンペーン純ロジックを import 解決する。
_HERE = os.path.dirname(os.path.abspath(__file__))
_CAMP = os.path.join(_HERE, "..", "reports", "situations_v1-eval-20260722")
if _CAMP not in sys.path:
    sys.path.insert(0, _CAMP)

import situations_common as sc  # noqa: E402


# ---------------------------------------------------------------------------
# 合成フィクスチャ
# ---------------------------------------------------------------------------
def _pso(ts, version="PSO-Snapshot/1.4", audio=None, humans=None, objects=None,
         geom="default"):
    fr = {
        "version": version,
        "ts": ts,
        "tracks": {
            "audio": [] if audio is None else audio,
            "humans": [] if humans is None else humans,
            "objects": [] if objects is None else objects,
        },
    }
    if geom == "default":
        fr["geom"] = {"overlap_path": False, "lane_alignment": False, "min_TTC_s": 99.0}
    elif geom is not None:
        fr["geom"] = geom
    # geom is None → geom キーなし(TTC 供給停止相当)
    return fr


def _clean_frames(n=3):
    return [_pso(float(i) * 0.5, audio=[{"aid": "A1", "type": "noise", "r_m": 2.6}])
            for i in range(n)]


def _label_gt_frame():
    """situations_v1 のラベル形 GT フレーム(補助 hazard/dynamics 付き)。"""
    return {
        "ts": 0.0,
        "t0": {"risk_tier": "danger"},
        "t1": {"state": "approach"},
        "t2": {"mode": "hazard_front", "role": "source_alarm", "relation": "approaching",
               "hazard": "critical", "dynamics": "closing"},
        "t3": {"hypothesis": "emergency", "scene_regime": "DEGRADING",
               "quality_regime": "DEGRADED"},
        "gt_origin": {"all": "world_derived"},
    }


# ---------------------------------------------------------------------------
# preflight: クリーン
# ---------------------------------------------------------------------------
def test_preflight_ok_clean():
    frames = _clean_frames(3)
    v = sc.preflight_validate(frames, gt_frame_count=3)
    assert v["ok"] is True
    assert v["reason"] is None


def test_preflight_deterministic():
    frames = _clean_frames(4)
    assert sc.preflight_validate(frames, 4) == sc.preflight_validate(frames, 4)


# ---------------------------------------------------------------------------
# preflight: 4 種の違反
# ---------------------------------------------------------------------------
def test_preflight_bad_version():
    frames = _clean_frames(3)
    frames[1]["version"] = "PSO-Garbage/9.9"
    v = sc.preflight_validate(frames, gt_frame_count=3)
    assert v["ok"] is False
    assert v["reason"] == "bad_version"


def test_preflight_bad_version_delta_prefix():
    # Delta 混入も PSO-Snapshot/ 始まりでない → bad_version 扱いで拒否。
    frames = _clean_frames(2)
    frames[0]["version"] = "PSO-Delta/1.4"
    v = sc.preflight_validate(frames, gt_frame_count=2)
    assert v["ok"] is False
    assert v["reason"] == "bad_version"


def test_preflight_ts_regression():
    frames = _clean_frames(3)
    frames[0]["ts"] = 0.0
    frames[1]["ts"] = 0.5
    frames[2]["ts"] = 0.3  # 後退
    v = sc.preflight_validate(frames, gt_frame_count=3)
    assert v["ok"] is False
    assert v["reason"] == "ts_regression"


def test_preflight_ts_equal_ok():
    # 単調非減少(等値許容)は違反でない。
    frames = _clean_frames(3)
    for f in frames:
        f["ts"] = 1.0
    v = sc.preflight_validate(frames, gt_frame_count=3)
    assert v["ok"] is True


def test_preflight_type_break_audio_dict():
    frames = _clean_frames(3)
    frames[2]["tracks"]["audio"] = {"broken": True}  # list でなく dict
    v = sc.preflight_validate(frames, gt_frame_count=3)
    assert v["ok"] is False
    assert v["reason"] == "type_break"


def test_preflight_type_break_element_not_dict():
    frames = _clean_frames(2)
    frames[0]["tracks"]["humans"] = [123]  # 要素が dict でない
    v = sc.preflight_validate(frames, gt_frame_count=2)
    assert v["ok"] is False
    assert v["reason"] == "type_break"


def test_preflight_type_break_tracks_not_dict():
    frames = _clean_frames(2)
    frames[1]["tracks"] = ["oops"]
    v = sc.preflight_validate(frames, gt_frame_count=2)
    assert v["ok"] is False
    assert v["reason"] == "type_break"


def test_preflight_frame_count_mismatch():
    frames = _clean_frames(3)
    v = sc.preflight_validate(frames, gt_frame_count=4)  # PSO 3 != GT 4
    assert v["ok"] is False
    assert v["reason"] == "frame_count_mismatch"


def test_preflight_frame_count_skipped_when_none():
    # gt_frame_count=None ならフレーム数検査はしない(他が健全なら ok)。
    frames = _clean_frames(3)
    assert sc.preflight_validate(frames, gt_frame_count=None)["ok"] is True


def test_preflight_missing_geom_is_not_violation():
    # geom 欠落(TTC 供給停止)は破損仕様であって契約違反ではない → ok のまま。
    frames = [_pso(float(i), geom=None) for i in range(3)]
    v = sc.preflight_validate(frames, gt_frame_count=3)
    assert v["ok"] is True


# ---------------------------------------------------------------------------
# version は書き換えない
# ---------------------------------------------------------------------------
def test_preflight_does_not_rewrite_version():
    frames = _clean_frames(3)
    frames[1]["version"] = "PSO-Garbage/9.9"
    sc.preflight_validate(frames, gt_frame_count=3)
    assert frames[1]["version"] == "PSO-Garbage/9.9"  # 洗浄されていない


def test_prepare_snaps_does_not_rewrite_version_or_mutate_source():
    src = _clean_frames(2)
    src[0]["version"] = "PSO-Snapshot/1.3"  # 受理される別バージョン
    out = sc.prepare_snaps(src)
    assert out[0]["version"] == "PSO-Snapshot/1.3"
    # 原本の tracks が prepare で破壊されていない
    assert src[0]["tracks"]["audio"] == [{"aid": "A1", "type": "noise", "r_m": 2.6}]


# ---------------------------------------------------------------------------
# prepare_snaps: geom 補完
# ---------------------------------------------------------------------------
def test_prepare_snaps_fills_missing_geom():
    frames = [_pso(0.0, geom=None)]
    out = sc.prepare_snaps(frames)
    assert out[0]["geom"]["min_TTC_s"] == 999.0
    assert out[0]["geom"]["overlap_path"] is False
    assert out[0]["geom"]["lane_alignment"] is False


def test_prepare_snaps_preserves_present_geom():
    frames = [_pso(0.0, geom={"min_TTC_s": 3.2, "overlap_path": True})]
    out = sc.prepare_snaps(frames)
    assert out[0]["geom"]["min_TTC_s"] == 3.2  # 既存値を上書きしない
    assert out[0]["geom"]["overlap_path"] is True


# ---------------------------------------------------------------------------
# gt_view: ラベル形パース(hazard/dynamics 無視)
# ---------------------------------------------------------------------------
def test_gt_view_maps_eight_layers():
    v = sc.gt_view(_label_gt_frame())
    assert v == {
        "risk_tier": "danger",
        "t1_state": "approach",
        "t2_mode": "hazard_front",
        "t2_role": "source_alarm",
        "t2_relation": "approaching",
        "t3_hypothesis": "emergency",
        "quality_regime": "DEGRADED",
        "scene_regime": "DEGRADING",
    }


def test_gt_view_ignores_hazard_and_dynamics():
    v = sc.gt_view(_label_gt_frame())
    assert "hazard" not in v
    assert "dynamics" not in v
    assert set(v.keys()) == set(sc.LAYERS)


def test_gt_view_missing_keys_become_none():
    v = sc.gt_view({"ts": 0.0})  # 層がすべて欠損
    assert all(v[layer] is None for layer in sc.LAYERS)


def test_gt_view_quality_scene_come_from_t3():
    # quality_regime / scene_regime が t3 配下から取れることを明示。
    fr = {"t3": {"hypothesis": "quiet_stable", "scene_regime": "STABLE",
                 "quality_regime": "GOOD"}}
    v = sc.gt_view(fr)
    assert v["quality_regime"] == "GOOD"
    assert v["scene_regime"] == "STABLE"
    assert v["t3_hypothesis"] == "quiet_stable"


# ---------------------------------------------------------------------------
# trace 組み立て / suite 分割
# ---------------------------------------------------------------------------
def test_assemble_trace_frames_aligns_by_index():
    views = [{"t2_mode": "quiet_standby"}, {"t2_mode": "hazard_front"}]
    gts = [_label_gt_frame(), _label_gt_frame()]
    frames = sc.assemble_trace_frames(views, gts)
    assert len(frames) == 2
    assert frames[0]["view"]["t2_mode"] == "quiet_standby"
    assert frames[0]["gt"]["t2_mode"] == "hazard_front"


def test_assemble_trace_frames_min_length():
    views = [{"t2_mode": "a"}, {"t2_mode": "b"}, {"t2_mode": "c"}]
    gts = [_label_gt_frame()]
    assert len(sc.assemble_trace_frames(views, gts)) == 1  # 捏造せず min 長


def test_partition_by_suite():
    trace = {"std-x-eval-00": [1], "crp-y-eval-01": [2], "std-z-eval-02": [3]}
    parts = sc.partition_by_suite(trace)
    assert set(parts.keys()) == {"std", "crp"}
    assert set(parts["std"].keys()) == {"std-x-eval-00", "std-z-eval-02"}


def test_suite_of():
    assert sc.suite_of("crp-violation-eval-02") == "crp"
    assert sc.suite_of("std-quiet_room-train-00") == "std"


# ---------------------------------------------------------------------------
# 統合スモーク(データルートが在るときだけ・無ければ skip)
# ---------------------------------------------------------------------------
_DATA = sc.DEFAULT_DATA_ROOT
_HAS_DATA = os.path.isdir(_DATA)


@pytest.mark.skipif(not _HAS_DATA, reason="situations_v1 データルート不在")
def test_integration_enumerate_counts():
    train = sc.enumerate_scenarios(_DATA, split="train")
    ev = sc.enumerate_scenarios(_DATA, split="eval")
    assert len(train) == 480  # 6 suite × 80
    assert len(ev) == 240     # 6 suite × 40
    train_viol = [r for r in train if r["contract_violation"]]
    eval_viol = [r for r in ev if r["contract_violation"]]
    assert len(train_viol) == 13
    assert len(eval_viol) == 5
    assert all(r["suite"] == "crp" for r in train_viol + eval_viol)


@pytest.mark.skipif(not _HAS_DATA, reason="situations_v1 データルート不在")
def test_integration_eval_violations_all_rejected():
    ev = sc.enumerate_scenarios(_DATA, split="eval")
    reasons = set()
    for r in ev:
        if not r["contract_violation"]:
            continue
        pso = sc.load_pso_frames(r["dir"])
        gtf = sc.load_gt_frames(r["dir"])
        v = sc.preflight_validate(pso, len(gtf))
        assert v["ok"] is False, f"{r['sid']} が拒否されなかった"
        reasons.add(v["reason"])
    # 5 本で 4 種のうち複数が現れる(frame_count が 2 本)。
    assert reasons <= set(sc.REJECT_REASONS)
    assert {"bad_version", "ts_regression", "type_break",
            "frame_count_mismatch"} & reasons
