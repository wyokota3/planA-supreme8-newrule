"""F-004-3: 指標定義／許容幅が欠落した呼び出しはエラーで停止する(適当な値を埋めない)。

specs/SPEC.md F-004-3:
  「指標定義／許容幅が欠落した呼び出しはエラーで停止する。」
specs/SPEC.md F-004 異常系:
  「指標定義・許容幅が未供給なら実行せず停止(適当な値を埋めない)。」
specs/TEST_STRATEGY.md F-004:
  「停止することのテストは(採点結果のテストと違い)先行可」。
decisions/0012-u10-evaluation-metrics.md / 0002:
  欠落時に値を捏造しない(F-004 異常系の精神)。

テストが前提とする supreme.harness の公開 API(設計裁量・指示で委任):
  harness.score(trace, metric_spec) -> ScoreResult
    metric_spec が None/未供給 → harness.MetricSpecMissingError で停止。
  harness.check_reproduction(run_a, run_b, *, eps_abs, eps_rel) -> ReproResult
    eps_abs/eps_rel が None/未供給 → harness.ToleranceMissingError で停止。

このファイルは「停止する」こと自体のテスト(SPEC 異常系)。採点の正しさは
test_F004_deterministic_scoring.py が担当する。
"""

import pytest

import fixtures_harness as fxh
from supreme import harness


def _trace():
    return fxh.trace_all_correct()


def _run():
    return fxh.repro_run(t3_posterior=0.5, stability=0.8, hypothesis="indoor_quiet")


# ---------------------------------------------------------------------------
# F-004-3: 指標定義欠落 → score が停止
# ---------------------------------------------------------------------------

def test_F004_3_score_with_none_metric_spec_raises():
    """F-004-3: metric_spec=None で score を呼ぶと MetricSpecMissingError で停止。

    適当なデフォルト指標を埋めて採点してはならない(SPEC 異常系)。
    """
    with pytest.raises(harness.MetricSpecMissingError):
        harness.score(_trace(), None)


def test_F004_3_score_without_metric_spec_argument_raises():
    """F-004-3: metric_spec を渡さず score(trace) を呼ぶと停止する。

    指標定義の未供給は黙って既定値で採点せず、エラーで止める。
    TypeError(引数不足)または MetricSpecMissingError のいずれかで停止すること。
    """
    with pytest.raises((harness.MetricSpecMissingError, TypeError)):
        harness.score(_trace())  # metric_spec を意図的に渡さない


def test_F004_3_score_does_not_fabricate_score_on_missing_spec():
    """F-004-3: 指標定義欠落時に「それらしいスコア」を返さない(捏造禁止)。

    None 指標で score を呼んで、例外ではなく ScoreResult 様のオブジェクトを
    返してしまう実装を禁止する。必ず例外で停止する。
    """
    raised = False
    try:
        harness.score(_trace(), None)
    except harness.MetricSpecMissingError:
        raised = True
    except Exception:
        # 他の例外でも「停止した」ことは満たす(値を埋めて返してはいない)
        raised = True
    assert raised, "指標定義 None で score が停止せず値を返した(捏造の疑い)"


# ---------------------------------------------------------------------------
# F-004-3: 許容幅欠落 → check_reproduction が停止
# ---------------------------------------------------------------------------

def test_F004_3_reproduction_with_none_eps_abs_raises():
    """F-004-3: eps_abs=None で再現判定を呼ぶと ToleranceMissingError で停止。"""
    with pytest.raises(harness.ToleranceMissingError):
        harness.check_reproduction(_run(), _run(), eps_abs=None, eps_rel=1e-6)


def test_F004_3_reproduction_with_none_eps_rel_raises():
    """F-004-3: eps_rel=None で再現判定を呼ぶと ToleranceMissingError で停止。"""
    with pytest.raises(harness.ToleranceMissingError):
        harness.check_reproduction(_run(), _run(), eps_abs=1e-9, eps_rel=None)


def test_F004_3_reproduction_without_tolerance_raises():
    """F-004-3: 許容幅を一切渡さず再現判定を呼ぶと停止する。

    黙って既定 ε を埋めて再現判定してはならない。
    ToleranceMissingError または TypeError(引数不足)で停止すること。
    """
    with pytest.raises((harness.ToleranceMissingError, TypeError)):
        harness.check_reproduction(_run(), _run())  # eps を意図的に渡さない


def test_F004_3_reproduction_does_not_fabricate_on_missing_tolerance():
    """F-004-3: 許容幅欠落時に再現判定結果を捏造して返さない。

    eps_abs/eps_rel が両方 None でも、適当な判定(reproduced=True 等)を
    返さず必ず停止する。
    """
    raised = False
    try:
        harness.check_reproduction(_run(), _run(), eps_abs=None, eps_rel=None)
    except harness.ToleranceMissingError:
        raised = True
    except Exception:
        raised = True
    assert raised, "許容幅 None で check_reproduction が停止せず値を返した(捏造の疑い)"
