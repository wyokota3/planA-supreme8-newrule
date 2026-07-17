"""F-005-1: 誤りの所在が項目別・クラス別に出力（混同行列・誤りフレーム一覧・正解率）。

specs/SPEC.md F-005-1:
  「弱い5項目それぞれについて、誤りの所在が項目別・クラス別に出力される」

対象の弱い5項目: t2_mode / t2_relation / t3_hypothesis / quality_regime / scene_regime

テストが前提とする supreme.erroran の公開 API:
  erroran.analyze(ingest_result) -> AnalysisResult
    .confusion_matrix(layer: str) -> dict[str, dict[str, int]]
        各 GT クラス×予測クラスの件数を持つ入れ子 dict。
        {"<gt_cls>": {"<pred_cls>": int, ...}, ...}
    .error_frames(layer: str) -> list[dict]
        誤りフレーム一覧。
        各要素: {"scenario_id": str, "ts": float, "pred": str, "gt": str}
    .accuracy(layer: str) -> float
        [0, 1] の正解率。
    .layers: list[str]
        分析した層名のリスト（弱い5項目が全て含まれる）。

  または:
  erroran.analyze(trace, canonical_records) -> AnalysisResult
    （ingest を内部的に行い結果を返す。上記と同様のインターフェース）
"""

import pytest

import fixtures_gt as fx
from supreme import erroran

# 弱い5項目の層名（テスト全体で共通）
WEAK_LAYERS = ["t2_mode", "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]


# ---------------------------------------------------------------------------
# ヘルパ: analyze を共通の方法で呼び出す
# ---------------------------------------------------------------------------

def _analyze_known_errors():
    """trace_with_known_errors を取込して AnalysisResult を返す共通ヘルパ。"""
    trace = fx.trace_with_known_errors()
    canonical = fx.canonical_records_for_trace()
    return erroran.analyze(trace, canonical)


def _analyze_perfect():
    """trace_perfect_2scenario を取込して AnalysisResult を返す共通ヘルパ。"""
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    return erroran.analyze(trace, canonical)


# ---------------------------------------------------------------------------
# F-005-1: 弱い5項目の全セクション存在確認
# ---------------------------------------------------------------------------

def test_F005_1_all_weak_layers_present_in_analysis():
    """F-005-1: 分析結果が弱い5項目を全て含む。

    AnalysisResult.layers に WEAK_LAYERS の5項目が全て含まれることを検証する。
    """
    result = _analyze_perfect()
    for layer in WEAK_LAYERS:
        assert layer in result.layers, f"弱い5項目 '{layer}' が分析結果に存在しない"


# ---------------------------------------------------------------------------
# F-005-1: 混同行列（confusion matrix）
# ---------------------------------------------------------------------------

def test_F005_1_confusion_matrix_structure_per_layer():
    """F-005-1: 各弱い5項目について混同行列（GT クラス×予測クラス）が取り出せる。

    confusion_matrix(layer) が dict[str, dict[str, int]] 形式で返ることを確認する。
    """
    result = _analyze_known_errors()
    for layer in WEAK_LAYERS:
        cm = result.confusion_matrix(layer)
        assert isinstance(cm, dict), f"{layer}: confusion_matrix が dict でない"
        for gt_cls, pred_dict in cm.items():
            assert isinstance(gt_cls, str)
            assert isinstance(pred_dict, dict)
            for pred_cls, count in pred_dict.items():
                assert isinstance(pred_cls, str)
                assert isinstance(count, int)
                assert count >= 0


def test_F005_1_confusion_matrix_t2_mode_has_expected_counts():
    """F-005-1: t2_mode の混同行列が既知の誤り数に一致する。

    trace_with_known_errors では sc1 フレーム 1.0 で t2_mode:
      view(予測)=conv_ongoing, gt=conv_request → 誤り1件
    confusion_matrix["conv_request"]["conv_ongoing"] == 1 を確認する。
    """
    result = _analyze_known_errors()
    cm = result.confusion_matrix("t2_mode")
    # conv_request を conv_ongoing と予測した件数は1
    assert cm.get("conv_request", {}).get("conv_ongoing", 0) == 1


def test_F005_1_confusion_matrix_t2_relation_has_expected_counts():
    """F-005-1: t2_relation の混同行列が既知の誤り数に一致する。

    trace_with_known_errors では sc2 フレーム 0.0 で t2_relation:
      view(予測)=near_user, gt=addressing_user → 誤り1件
    confusion_matrix["addressing_user"]["near_user"] == 1 を確認する。
    """
    result = _analyze_known_errors()
    cm = result.confusion_matrix("t2_relation")
    assert cm.get("addressing_user", {}).get("near_user", 0) == 1


def test_F005_1_confusion_matrix_quality_regime_has_expected_counts():
    """F-005-1: quality_regime の混同行列が既知の誤り数に一致する。

    trace_with_known_errors では sc2 フレーム 1.0 で quality_regime:
      view(予測)=BLOCK, gt=GOOD → 誤り1件
    confusion_matrix["GOOD"]["BLOCK"] == 1 を確認する。
    """
    result = _analyze_known_errors()
    cm = result.confusion_matrix("quality_regime")
    assert cm.get("GOOD", {}).get("BLOCK", 0) == 1


def test_F005_1_confusion_matrix_scene_regime_has_expected_counts():
    """F-005-1: scene_regime の混同行列が既知の誤り数に一致する。

    trace_with_known_errors では sc2 フレーム 2.0 で scene_regime:
      view(予測)=MOVING, gt=STABLE → 誤り1件
    confusion_matrix["STABLE"]["MOVING"] == 1 を確認する。
    """
    result = _analyze_known_errors()
    cm = result.confusion_matrix("scene_regime")
    assert cm.get("STABLE", {}).get("MOVING", 0) == 1


def test_F005_1_confusion_matrix_t3_hypothesis_no_error():
    """F-005-1: t3_hypothesis の混同行列で誤りゼロの場合は正解のみ。

    trace_with_known_errors では t3_hypothesis の誤りはない。
    diagonal entries（gt==pred）のみに件数が入り、off-diagonal は0である。
    """
    result = _analyze_known_errors()
    cm = result.confusion_matrix("t3_hypothesis")
    for gt_cls, pred_dict in cm.items():
        for pred_cls, count in pred_dict.items():
            if gt_cls != pred_cls:
                assert count == 0, (
                    f"t3_hypothesis: GT={gt_cls}, pred={pred_cls} に誤り{count}件が記録されている"
                )


def test_F005_1_confusion_matrix_diagonal_equals_correct_count():
    """F-005-1: 混同行列の対角成分の合計が正解フレーム数と一致する。

    trace_perfect（全フレーム正解）の場合、全層で off-diagonal が 0 であることを確認。
    """
    result = _analyze_perfect()
    for layer in WEAK_LAYERS:
        cm = result.confusion_matrix(layer)
        for gt_cls, pred_dict in cm.items():
            for pred_cls, count in pred_dict.items():
                if gt_cls != pred_cls:
                    assert count == 0, (
                        f"{layer}: GT={gt_cls}, pred={pred_cls} に誤りが記録されている（全正解フィクスチャ）"
                    )


# ---------------------------------------------------------------------------
# F-005-1: 誤りフレーム一覧
# ---------------------------------------------------------------------------

def test_F005_1_error_frames_structure_per_layer():
    """F-005-1: 各弱い5項目について誤りフレーム一覧が取り出せる。

    error_frames(layer) が list[dict] 形式で、各要素が
    {"scenario_id": str, "ts": float, "pred": str, "gt": str} を持つことを確認する。
    """
    result = _analyze_known_errors()
    for layer in WEAK_LAYERS:
        frames = result.error_frames(layer)
        assert isinstance(frames, list), f"{layer}: error_frames が list でない"
        for item in frames:
            assert "scenario_id" in item
            assert "ts" in item
            assert "pred" in item
            assert "gt" in item
            assert isinstance(item["scenario_id"], str)
            assert isinstance(item["ts"], float)
            assert isinstance(item["pred"], str)
            assert isinstance(item["gt"], str)


def test_F005_1_error_frames_t2_mode_contains_known_error():
    """F-005-1: t2_mode 誤りフレーム一覧が既知の誤りフレームを含む。

    trace_with_known_errors の sc1 フレーム 1.0 で t2_mode 誤りがある。
    """
    result = _analyze_known_errors()
    frames = result.error_frames("t2_mode")
    assert any(
        f["scenario_id"] == "sc1" and f["ts"] == 1.0
        and f["pred"] == "conv_ongoing" and f["gt"] == "conv_request"
        for f in frames
    ), "t2_mode 誤りフレーム（sc1, ts=1.0）が error_frames に含まれていない"


def test_F005_1_error_frames_count_matches_expected():
    """F-005-1: 各層の誤りフレーム数が既知の誤り数と一致する。

    trace_with_known_errors の既知誤り数:
      t2_mode: 1, t2_relation: 1, t3_hypothesis: 0, quality_regime: 1, scene_regime: 1
    """
    result = _analyze_known_errors()
    expected = {
        "t2_mode": 1,
        "t2_relation": 1,
        "t3_hypothesis": 0,
        "quality_regime": 1,
        "scene_regime": 1,
    }
    for layer, expected_count in expected.items():
        actual_count = len(result.error_frames(layer))
        assert actual_count == expected_count, (
            f"{layer}: error_frames の件数が {actual_count}、期待値は {expected_count}"
        )


def test_F005_1_error_frames_empty_when_perfect():
    """F-005-1: 全フレーム正解の trace では全層の error_frames が空。"""
    result = _analyze_perfect()
    for layer in WEAK_LAYERS:
        frames = result.error_frames(layer)
        assert frames == [], f"{layer}: 全正解フィクスチャで error_frames が空でない: {frames}"


# ---------------------------------------------------------------------------
# F-005-1: 正解率（accuracy）
# ---------------------------------------------------------------------------

def test_F005_1_accuracy_perfect_is_1():
    """F-005-1: 全フレーム正解の trace では全弱い5項目の accuracy が 1.0。"""
    result = _analyze_perfect()
    for layer in WEAK_LAYERS:
        acc = result.accuracy(layer)
        assert acc == pytest.approx(1.0), f"{layer}: 全正解フィクスチャの accuracy が 1.0 でない（{acc}）"


def test_F005_1_accuracy_t2_mode_matches_expected():
    """F-005-1: t2_mode の accuracy が既知の誤り数から計算した期待値と一致する。

    合計フレーム数 = 2シナリオ×3フレーム = 6
    t2_mode 誤り = 1
    期待 accuracy = 5/6 ≈ 0.8333...
    """
    result = _analyze_known_errors()
    acc = result.accuracy("t2_mode")
    expected = 5 / 6
    assert acc == pytest.approx(expected, rel=1e-5), (
        f"t2_mode accuracy={acc}, 期待値≈{expected}"
    )


def test_F005_1_accuracy_t2_relation_matches_expected():
    """F-005-1: t2_relation の accuracy が期待値と一致する。

    誤り = 1, 合計 = 6 → expected = 5/6
    """
    result = _analyze_known_errors()
    acc = result.accuracy("t2_relation")
    assert acc == pytest.approx(5 / 6, rel=1e-5)


def test_F005_1_accuracy_t3_hypothesis_is_1():
    """F-005-1: t3_hypothesis 誤りゼロの場合 accuracy=1.0。"""
    result = _analyze_known_errors()
    acc = result.accuracy("t3_hypothesis")
    assert acc == pytest.approx(1.0)


def test_F005_1_accuracy_quality_regime_matches_expected():
    """F-005-1: quality_regime の accuracy が期待値と一致する。

    誤り = 1, 合計 = 6 → expected = 5/6
    """
    result = _analyze_known_errors()
    acc = result.accuracy("quality_regime")
    assert acc == pytest.approx(5 / 6, rel=1e-5)


def test_F005_1_accuracy_scene_regime_matches_expected():
    """F-005-1: scene_regime の accuracy が期待値と一致する。

    誤り = 1, 合計 = 6 → expected = 5/6
    """
    result = _analyze_known_errors()
    acc = result.accuracy("scene_regime")
    assert acc == pytest.approx(5 / 6, rel=1e-5)


def test_F005_1_accuracy_range_is_0_to_1():
    """F-005-1: accuracy が常に [0, 1] の範囲にある。"""
    result = _analyze_known_errors()
    for layer in WEAK_LAYERS:
        acc = result.accuracy(layer)
        assert 0.0 <= acc <= 1.0, f"{layer}: accuracy={acc} が [0,1] 外"


# ---------------------------------------------------------------------------
# F-005-1: クラス別誤り集計
# ---------------------------------------------------------------------------

def test_F005_1_confusion_matrix_total_equals_frame_count():
    """F-005-1: 混同行列の全セルの合計がフレーム総数と一致する。

    全フレームは6件（2シナリオ×3フレーム）。混同行列のセル合計も6であるべき。
    """
    result = _analyze_known_errors()
    for layer in WEAK_LAYERS:
        cm = result.confusion_matrix(layer)
        total = sum(count for pred_dict in cm.values() for count in pred_dict.values())
        assert total == 6, f"{layer}: 混同行列の合計={total}、期待値=6"
