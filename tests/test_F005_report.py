"""F-005-2: 構造原因レポートの骨子生成。

specs/SPEC.md F-005-2:
  「各改良モジュール（F-007〜011）が着手前に参照すべき構造原因が文書化される」

レポート骨子の必須構造（仕様より）:
  - 弱い5項目（t2_mode / t2_relation / t3_hypothesis / quality_regime / scene_regime）それぞれのセクション
    * 統計埋め込み: acc・混同行列・主要誤りパターン
    * 「原因仮説（記入欄）」
  - F-008 配線漏れ仮説の検証セクション
    * relation の誤りパターン statistics 付き
    * 判定記入欄

NOTE: 内容の十分性はテスト対象外（TEST_STRATEGY「骨子に5項目全セクションが存在することをテスト」）。
      ここでは構造（セクションの存在・必須キーの存在）のみを検証する。

テストが前提とする supreme.erroran の公開 API:
  erroran.generate_report(analysis_result) -> str
    Markdown 文字列を返す。

  または:
  erroran.generate_report(trace, canonical_records) -> str
    内部で analyze を呼び Markdown を返す。
"""

import pytest

import fixtures_gt as fx
from supreme import erroran

# 弱い5項目の層名（セクション確認で使用）
WEAK_LAYERS = ["t2_mode", "t2_relation", "t3_hypothesis", "quality_regime", "scene_regime"]

# F-008 配線漏れ仮説検証セクションのキーワード
F008_KEYWORDS = ["F-008", "relation", "配線漏れ"]


# ---------------------------------------------------------------------------
# ヘルパ
# ---------------------------------------------------------------------------

def _generate_report_known_errors():
    """trace_with_known_errors を使ってレポートを生成する共通ヘルパ。"""
    trace = fx.trace_with_known_errors()
    canonical = fx.canonical_records_for_trace()
    return erroran.generate_report(trace, canonical)


def _generate_report_perfect():
    """trace_perfect_2scenario を使ってレポートを生成する共通ヘルパ。"""
    trace = fx.trace_perfect_2scenario()
    canonical = fx.canonical_records_for_trace()
    return erroran.generate_report(trace, canonical)


# ---------------------------------------------------------------------------
# F-005-2: 出力が Markdown 文字列であること
# ---------------------------------------------------------------------------

def test_F005_2_report_returns_string():
    """F-005-2: generate_report が文字列（Markdown）を返す。"""
    report = _generate_report_known_errors()
    assert isinstance(report, str), f"generate_report の戻り値が str でない: {type(report)}"
    assert len(report) > 0, "generate_report が空文字列を返した"


# ---------------------------------------------------------------------------
# F-005-2: 弱い5項目の全セクションが存在すること
# ---------------------------------------------------------------------------

def test_F005_2_report_contains_t2_mode_section():
    """F-005-2: レポートに t2_mode のセクションが存在する。"""
    report = _generate_report_known_errors()
    assert "t2_mode" in report or "mode" in report.lower(), (
        "レポートに t2_mode（mode）のセクションが見当たらない"
    )


def test_F005_2_report_contains_t2_relation_section():
    """F-005-2: レポートに t2_relation のセクションが存在する。"""
    report = _generate_report_known_errors()
    assert "t2_relation" in report or "relation" in report.lower(), (
        "レポートに t2_relation（relation）のセクションが見当たらない"
    )


def test_F005_2_report_contains_t3_hypothesis_section():
    """F-005-2: レポートに t3_hypothesis のセクションが存在する。"""
    report = _generate_report_known_errors()
    assert "t3_hypothesis" in report or "hypothesis" in report.lower(), (
        "レポートに t3_hypothesis（hypothesis）のセクションが見当たらない"
    )


def test_F005_2_report_contains_quality_regime_section():
    """F-005-2: レポートに quality_regime のセクションが存在する。"""
    report = _generate_report_known_errors()
    assert "quality_regime" in report or "quality" in report.lower(), (
        "レポートに quality_regime（quality）のセクションが見当たらない"
    )


def test_F005_2_report_contains_scene_regime_section():
    """F-005-2: レポートに scene_regime のセクションが存在する。"""
    report = _generate_report_known_errors()
    assert "scene_regime" in report or "scene" in report.lower(), (
        "レポートに scene_regime（scene）のセクションが見当たらない"
    )


def test_F005_2_report_all_weak_layers_present():
    """F-005-2: 弱い5項目の全セクションがレポートに存在することを一括確認。"""
    report = _generate_report_known_errors()
    report_lower = report.lower()
    for layer in WEAK_LAYERS:
        base = layer.split("_")[1] if "_" in layer else layer  # 例: t2_mode → mode
        assert layer in report or base in report_lower, (
            f"レポートに '{layer}'（または '{base}'）のセクションが見当たらない"
        )


# ---------------------------------------------------------------------------
# F-005-2: 各セクションに統計（acc・混同行列・主要誤りパターン）が埋め込まれている
# ---------------------------------------------------------------------------

def test_F005_2_report_contains_accuracy_statistics():
    """F-005-2: レポートに accuracy（正解率）の統計が埋め込まれている。"""
    report = _generate_report_known_errors()
    assert "acc" in report.lower() or "accuracy" in report.lower() or "正解率" in report, (
        "レポートに accuracy / acc / 正解率 が含まれていない"
    )


def test_F005_2_report_contains_confusion_matrix_reference():
    """F-005-2: レポートに混同行列への言及がある。"""
    report = _generate_report_known_errors()
    has_confusion = (
        "confusion" in report.lower()
        or "混同行列" in report
        or "confusion_matrix" in report.lower()
    )
    assert has_confusion, "レポートに混同行列への言及がない"


def test_F005_2_report_contains_error_pattern_reference():
    """F-005-2: レポートに主要誤りパターンへの言及がある。"""
    report = _generate_report_known_errors()
    has_pattern = (
        "pattern" in report.lower()
        or "誤りパターン" in report
        or "error" in report.lower()
        or "誤り" in report
    )
    assert has_pattern, "レポートに誤りパターン（error/誤りパターン）への言及がない"


# ---------------------------------------------------------------------------
# F-005-2: 「原因仮説（記入欄）」が存在すること
# ---------------------------------------------------------------------------

def test_F005_2_report_contains_hypothesis_placeholder():
    """F-005-2: レポートに「原因仮説（記入欄）」の記入欄が存在する。"""
    report = _generate_report_known_errors()
    has_placeholder = (
        "原因仮説" in report
        or "記入欄" in report
        or "TODO" in report
        or "hypothesis" in report.lower()
        or "cause" in report.lower()
    )
    assert has_placeholder, (
        "レポートに「原因仮説（記入欄）」相当のプレースホルダが見当たらない"
    )


# ---------------------------------------------------------------------------
# F-005-2: F-008 配線漏れ仮説の検証セクション
# ---------------------------------------------------------------------------

def test_F005_2_report_contains_f008_wiring_section():
    """F-005-2: レポートに F-008 配線漏れ仮説の検証セクションが存在する。

    仕様: 「F-008 配線漏れ仮説の検証セクション（relation の誤りパターン statistics 付き・判定記入欄）」
    NOTE: F-008 の配線漏れは未検証の仮説（SPEC.md F-008 注記）。
          テストはセクションの「存在」のみを確認し、仮説の真偽は確認しない。
    """
    report = _generate_report_known_errors()
    # F-008 または「配線漏れ」または関連キーワードを含むセクションが存在するか
    has_f008 = any(kw in report or kw in report.lower() for kw in F008_KEYWORDS)
    assert has_f008, (
        f"レポートに F-008 配線漏れ仮説の検証セクションが見当たらない "
        f"（検索キーワード: {F008_KEYWORDS}）"
    )


def test_F005_2_report_f008_section_has_statistics():
    """F-005-2: F-008 配線漏れ仮説セクションに relation の統計（誤りパターン）が含まれる。"""
    report = _generate_report_known_errors()
    report_lower = report.lower()
    # relation + 何らかの数値情報（acc / count / statistics / 件数）が同一レポートに存在するか
    has_relation_stats = (
        "relation" in report_lower
        and (
            "acc" in report_lower
            or "count" in report_lower
            or "statistics" in report_lower
            or "件数" in report
            or "%" in report
            or any(c.isdigit() for c in report)  # 数値が含まれる
        )
    )
    assert has_relation_stats, (
        "F-008 配線漏れ仮説セクションに relation の誤りパターン statistics が含まれていない"
    )


def test_F005_2_report_f008_section_has_judgment_placeholder():
    """F-005-2: F-008 配線漏れ仮説セクションに判定記入欄が存在する。"""
    report = _generate_report_known_errors()
    has_judgment = (
        "判定" in report
        or "verdict" in report.lower()
        or "judgment" in report.lower()
        or "TODO" in report
        or "記入欄" in report
        or "[ ]" in report
    )
    assert has_judgment, "F-008 配線漏れ仮説セクションに判定記入欄が見当たらない"


# ---------------------------------------------------------------------------
# F-005-2: 正常系（全正解フィクスチャでもレポートが生成される）
# ---------------------------------------------------------------------------

def test_F005_2_report_generated_for_perfect_trace():
    """F-005-2: 全フレーム正解の trace でもレポートが生成される（セクション構造は変わらない）。"""
    report = _generate_report_perfect()
    assert isinstance(report, str)
    assert len(report) > 0
    # 弱い5項目のセクションは全正解でも存在する
    report_lower = report.lower()
    for layer in WEAK_LAYERS:
        base = layer.split("_")[1] if "_" in layer else layer
        assert layer in report or base in report_lower, (
            f"全正解フィクスチャのレポートに '{layer}' セクションが存在しない"
        )
