"""F-005: baseline 取込＋突合（取込と突合の整合検証）。

specs/SPEC.md F-005 境界条件:
  「取り込めるのは baseline 側の GT と F-001 スキーマが突合できる場合のみ」

本ファイルがカバーする受け入れ条件:
  F-005-1（部分）: 取込フェーズ。trace と canonical GT の整合検証。
    - t2_mode / t2_relation: canonical 確率分布の argmax と trace gt ラベルの一致
    - t3_hypothesis / quality_regime / scene_regime: 文字列フィールドの完全一致
    - (scenario_id, ts) でフレーム対応
    - 不整合があれば取込を拒否し、どのフレーム・どの層が不整合かを報告

テストが前提とする supreme.erroran の公開 API:
  erroran.ingest(trace, canonical_records) -> IngestResult
    .ok: bool（全フレーム整合すれば True）
    .mismatches: list[dict]（不整合フレーム情報）
      各要素: {
        "scenario_id": str,
        "ts": float,
        "layer": str,  # 不整合の層名（例 "t2_mode"）
        "trace_gt": str,  # trace の gt ラベル
        "canonical": str | dict,  # canonical GT の値（分布または文字列）
      }
    .missing_frames: list[dict]  # trace にあって canonical に無いフレーム
      各要素: {"scenario_id": str, "ts": float}
    .extra_frames: list[dict]  # canonical にあって trace に無いフレーム
      各要素: {"scenario_id": str, "ts": float}

  erroran.IngestError: 取込を拒否する際に発出する例外
    .mismatches: list[dict]（不整合フレーム情報、上と同形）
    .missing_frames: list[dict]
    .extra_frames: list[dict]
"""

import pytest

import fixtures_gt as fx
from supreme import erroran


# ---------------------------------------------------------------------------
# 正常系: 整合する trace と canonical GT
# ---------------------------------------------------------------------------

def test_F005_1_ingest_consistent_trace_ok():
    """F-005-1: trace の gt と canonical GT が全フレーム整合していれば取込 ok。

    2シナリオ×3フレーム、全フレームの弱い5項目が canonical GT と一致する
    フィクスチャで ingest が ok=True を返すことを確認する。
    """
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    result = erroran.ingest(trace, canonical)
    assert result.ok is True
    assert result.mismatches == []
    assert result.missing_frames == []
    assert result.extra_frames == []


def test_F005_1_ingest_with_known_errors_still_ok_if_gt_consistent():
    """F-005-1: trace の view が gt と異なっていても gt と canonical の整合には影響しない。

    trace_with_known_errors は view≠gt だが、gt ラベルは canonical GT と一致するため
    ingest は ok=True を返す（view の誤りは分析フェーズで扱う）。
    """
    trace = fx.trace_with_known_errors()
    canonical = fx.canonical_records_for_trace()
    result = erroran.ingest(trace, canonical)
    assert result.ok is True
    assert result.mismatches == []


# ---------------------------------------------------------------------------
# 突合: t2_mode の argmax 一致ルール
# ---------------------------------------------------------------------------

def test_F005_1_ingest_mode_argmax_mismatch_rejected():
    """F-005-1: canonical の t2_mode argmax が trace gt ラベルと一致しない場合は取込拒否。

    sc1 フレーム 0.0 の canonical mode argmax を 'conv_ongoing' にする（trace gt='conv_request'）。
    これは不整合なので ingest は ok=False または IngestError を送出する。
    """
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    # sc1 フレーム 0.0 の mode 分布を書き換える
    sc1_frames = canonical[0]["gt"]["frames"]
    target_frame = next(f for f in sc1_frames if f["ts"] == 0.0)
    # argmax を conv_ongoing に変更（trace gt = conv_request なので不整合）
    for k in target_frame["t2"]["mode"]:
        target_frame["t2"]["mode"][k] = 0.0
    target_frame["t2"]["mode"]["conv_ongoing"] = 1.0

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False, "argmax 不整合があるのに ok=True が返った"
        # 不整合の場所が報告される
        assert len(result.mismatches) >= 1
        mismatch = result.mismatches[0]
        assert mismatch["scenario_id"] == "sc1"
        assert mismatch["ts"] == 0.0
        assert mismatch["layer"] == "t2_mode"
    except erroran.IngestError as e:
        assert len(e.mismatches) >= 1
        mismatch = e.mismatches[0]
        assert mismatch["scenario_id"] == "sc1"
        assert mismatch["layer"] == "t2_mode"


def test_F005_1_ingest_mode_argmax_tie_included_passes():
    """F-005-1: canonical t2_mode で同率最大が複数の場合、trace gt ラベルがその集合に含まれれば一致。

    conv_request と conv_ongoing を同率最大（0.5）にし、trace gt = conv_request とする。
    trace gt が最大値集合に含まれるため ok=True。
    """
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    sc1_frames = canonical[0]["gt"]["frames"]
    target_frame = next(f for f in sc1_frames if f["ts"] == 0.0)
    # conv_request と conv_ongoing を同率最大に設定
    for k in target_frame["t2"]["mode"]:
        target_frame["t2"]["mode"][k] = 0.0
    target_frame["t2"]["mode"]["conv_request"] = 0.5
    target_frame["t2"]["mode"]["conv_ongoing"] = 0.5
    # trace gt = conv_request → 最大値集合 {conv_request, conv_ongoing} に含まれる

    result = erroran.ingest(trace, canonical)
    assert result.ok is True
    assert result.mismatches == []


def test_F005_1_ingest_mode_argmax_tie_not_included_rejected():
    """F-005-1: canonical t2_mode の同率最大の集合に trace gt ラベルが含まれない場合は不整合。

    conv_ongoing と uncertain を同率最大（0.5）にし、trace gt = conv_request とする。
    trace gt が最大値集合に含まれないため不整合。
    """
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    sc1_frames = canonical[0]["gt"]["frames"]
    target_frame = next(f for f in sc1_frames if f["ts"] == 0.0)
    for k in target_frame["t2"]["mode"]:
        target_frame["t2"]["mode"][k] = 0.0
    target_frame["t2"]["mode"]["conv_ongoing"] = 0.5
    target_frame["t2"]["mode"]["uncertain"] = 0.5
    # trace gt = conv_request → 最大値集合 {conv_ongoing, uncertain} に含まれない

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
    except erroran.IngestError:
        pass  # IngestError 送出も可


# ---------------------------------------------------------------------------
# 突合: t2_relation の argmax 一致ルール
# ---------------------------------------------------------------------------

def test_F005_1_ingest_relation_argmax_mismatch_rejected():
    """F-005-1: canonical の t2_relation argmax が trace gt ラベルと一致しない場合は取込拒否。

    sc2 フレーム 0.0 の canonical relations argmax を 'near_user' にする（trace gt='addressing_user'）。
    """
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    sc2_frames = canonical[1]["gt"]["frames"]
    target_frame = next(f for f in sc2_frames if f["ts"] == 0.0)
    for k in target_frame["t2"]["relations"]:
        target_frame["t2"]["relations"][k] = 0.0
    target_frame["t2"]["relations"]["near_user"] = 1.0  # trace gt = addressing_user なので不整合

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
        assert any(m["layer"] == "t2_relation" for m in result.mismatches)
    except erroran.IngestError as e:
        assert any(m["layer"] == "t2_relation" for m in e.mismatches)


# ---------------------------------------------------------------------------
# 突合: 文字列フィールド（t3_hypothesis / quality_regime / scene_regime）
# ---------------------------------------------------------------------------

def test_F005_1_ingest_hypothesis_mismatch_rejected():
    """F-005-1: canonical t3.hypothesis が trace gt と異なる場合は取込拒否。"""
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    sc1_frames = canonical[0]["gt"]["frames"]
    target_frame = next(f for f in sc1_frames if f["ts"] == 0.0)
    target_frame["t3"]["hypothesis"] = "outdoor_traffic"  # trace gt = indoor_quiet なので不整合

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
        assert any(m["layer"] == "t3_hypothesis" for m in result.mismatches)
    except erroran.IngestError as e:
        assert any(m["layer"] == "t3_hypothesis" for m in e.mismatches)


def test_F005_1_ingest_quality_regime_mismatch_rejected():
    """F-005-1: canonical t3.quality_regime が trace gt と異なる場合は取込拒否。"""
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    sc1_frames = canonical[0]["gt"]["frames"]
    target_frame = next(f for f in sc1_frames if f["ts"] == 0.0)
    target_frame["t3"]["quality_regime"] = "BLOCK"  # trace gt = GOOD なので不整合

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
        assert any(m["layer"] == "quality_regime" for m in result.mismatches)
    except erroran.IngestError as e:
        assert any(m["layer"] == "quality_regime" for m in e.mismatches)


def test_F005_1_ingest_scene_regime_mismatch_rejected():
    """F-005-1: canonical t3.scene_regime が trace gt と異なる場合は取込拒否。"""
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    sc1_frames = canonical[0]["gt"]["frames"]
    target_frame = next(f for f in sc1_frames if f["ts"] == 0.0)
    target_frame["t3"]["scene_regime"] = "MOVING"  # trace gt = STABLE なので不整合

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
        assert any(m["layer"] == "scene_regime" for m in result.mismatches)
    except erroran.IngestError as e:
        assert any(m["layer"] == "scene_regime" for m in e.mismatches)


# ---------------------------------------------------------------------------
# 突合: フレーム対応（trace に無い / canonical に無い）
# ---------------------------------------------------------------------------

def test_F005_1_ingest_missing_frame_in_canonical_reported():
    """F-005-1: trace にあって canonical に無い (scenario_id, ts) は missing_frames として報告。"""
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    # sc1 の canonical からフレーム 2.0 を削除する
    canonical[0]["gt"]["frames"] = [
        f for f in canonical[0]["gt"]["frames"] if f["ts"] != 2.0
    ]

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
        assert any(
            m["scenario_id"] == "sc1" and m["ts"] == 2.0
            for m in result.missing_frames
        )
    except erroran.IngestError as e:
        assert any(
            m["scenario_id"] == "sc1" and m["ts"] == 2.0
            for m in e.missing_frames
        )


def test_F005_1_ingest_extra_frame_in_canonical_reported():
    """F-005-1: canonical にあって trace に無い (scenario_id, ts) は extra_frames として報告。"""
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    # trace の sc1 からフレーム 2.0 を削除する
    trace["sc1"] = [f for f in trace["sc1"] if f["ts"] != 2.0]

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
        assert any(
            m["scenario_id"] == "sc1" and m["ts"] == 2.0
            for m in result.extra_frames
        )
    except erroran.IngestError as e:
        assert any(
            m["scenario_id"] == "sc1" and m["ts"] == 2.0
            for m in e.extra_frames
        )


def test_F005_1_ingest_multiple_mismatches_all_reported():
    """F-005-1: 不整合が複数フレームにまたがる場合、全不整合箇所が報告される。"""
    import copy
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    # sc1 フレーム 0.0: mode 不整合
    sc1_frames = canonical[0]["gt"]["frames"]
    f0 = next(f for f in sc1_frames if f["ts"] == 0.0)
    for k in f0["t2"]["mode"]:
        f0["t2"]["mode"][k] = 0.0
    f0["t2"]["mode"]["conv_ongoing"] = 1.0
    # sc2 フレーム 1.0: quality_regime 不整合
    sc2_frames = canonical[1]["gt"]["frames"]
    f1 = next(f for f in sc2_frames if f["ts"] == 1.0)
    f1["t3"]["quality_regime"] = "BLOCK"  # trace gt = GOOD

    try:
        result = erroran.ingest(trace, canonical)
        assert result.ok is False
        assert len(result.mismatches) >= 2
    except erroran.IngestError as e:
        assert len(e.mismatches) >= 2
